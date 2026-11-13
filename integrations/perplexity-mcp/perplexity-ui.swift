// Native, visible accessibility automation for the user-requested Perplexity session driver.
import Foundation
import AppKit
import ApplicationServices
import CryptoKit

struct UIError: Error { let message:String }
func attr(_ e:AXUIElement,_ key:String)->CFTypeRef? { var value:CFTypeRef?;return AXUIElementCopyAttributeValue(e,key as CFString,&value) == .success ? value:nil }
func string(_ value:CFTypeRef?)->String {if let v=value as? NSAttributedString{return v.string};return value as? String ?? ""}
func label(_ e:AXUIElement)->String {for key in ["AXDescription","AXAttributedDescription","AXTitle","AXValue","AXAttributedValue"] {let s=string(attr(e,key));if !s.isEmpty{return s}};return ""}
func isConversationTab(_ e:AXUIElement)->Bool {
 var names:CFArray?;AXUIElementCopyActionNames(e,&names)
 return (names as? [String] ?? []).contains{$0.contains("关闭标签页") || $0.lowercased().contains("close tab")}
}
func descendants(_ root:AXUIElement)->[AXUIElement] {
 var result:[AXUIElement]=[],seen:[CFHashCode:[AXUIElement]]=[:]
 func walk(_ e:AXUIElement,_ depth:Int) {let hash=CFHash(e);if depth>35 || result.count>=4000 || (seen[hash] ?? []).contains(where:{CFEqual($0,e)}){return};seen[hash,default:[]].append(e);result.append(e);for c in attr(e,"AXChildren") as? [AXUIElement] ?? [] {walk(c,depth+1)}}
 walk(root,0);return result
}
func window()throws->AXUIElement {
 guard let app=NSWorkspace.shared.runningApplications.first(where:{$0.bundleIdentifier=="ai.perplexity.macv3"}) else {throw UIError(message:"Perplexity is not running")}
 let ax=AXUIElementCreateApplication(app.processIdentifier)
 guard let w=(attr(ax,"AXWindows") as? [AXUIElement] ?? []).first(where:{string(attr($0,"AXIdentifier"))=="threads-window"}) else {throw UIError(message:"Perplexity main conversation window is unavailable; check Accessibility permission")}
 return w
}
func snapshot()throws->[String:Any] {
 let all=descendants(try window())
 let groups=all.filter{string(attr($0,"AXRole"))=="AXOpaqueProviderGroup"}
 let messageNodes=groups.map{descendants($0)}.max(by:{$0.count<$1.count}) ?? []
 let texts=messageNodes.filter{string(attr($0,"AXRole"))=="AXStaticText"}.map{label($0)}.filter{!$0.isEmpty}
 let body=texts.joined(separator:"\n")
 if body.utf8.count>750000 {throw UIError(message:"Visible conversation exceeds the driver's 750 KiB observation limit")}
 let selected=all.filter{string(attr($0,"AXRole"))=="AXButton" && (attr($0,"AXSelected") as? Bool)==true}.map{label($0)}
 let buttons=all.filter{string(attr($0,"AXRole"))=="AXButton"}
 let busy=buttons.contains{label($0)=="player-stop-filled" || string(attr($0,"AXHelp"))=="停止" || string(attr($0,"AXHelp"))=="Stop"}
 let input=all.first{string(attr($0,"AXRole"))=="AXTextArea"}
 let connectors=all.filter{["AXImage","AXStaticText"].contains(string(attr($0,"AXRole")))}.map{string(attr($0,"AXHelp"))}.filter{$0.hasPrefix("Codex Loop Mac")}
 return ["selected":selected,"messages":texts,"text":body,"text_sha256":SHA256.hash(data:Data(body.utf8)).map{String(format:"%02x",$0)}.joined(),"busy":busy,"input":input.map{string(attr($0,"AXValue"))} ?? "","connectors":Array(Set(connectors))]
}
func bound(_ state:[String:Any],_ expected:String,_ allowNew:Bool)->Bool {
 let selected=state["selected"] as? [String] ?? []
 if selected.contains(where:{$0.hasPrefix(expected)}) {return true}
 return allowNew  &&  (state["text"] as? String ?? "").isEmpty  &&  selected.contains(where:{["新建会话","New thread","New Thread"].contains($0)})
}
func send(_ request:[String:Any])throws->[String:Any] {
 guard let expected=request["session_marker"] as? String,expected.hasPrefix("[PCL:"),let text=request["text"] as? String,!text.isEmpty else {throw UIError(message:"Missing explicit session marker or text")}
 let before=try snapshot(),allowNew=request["allow_new_chat"] as? Bool ?? false
 guard bound(before,expected,allowNew) else {throw UIError(message:"Selected conversation does not match the bound task")}
 guard !(before["busy"] as? Bool ?? true) else {throw UIError(message:"Perplexity is still generating")}
 let existingDraft=request["allow_existing_draft"] as? Bool == true && before["input"] as? String == text
 guard (before["input"] as? String ?? "").isEmpty || existingDraft else {throw UIError(message:"Composer contains a user draft; it was not overwritten")}
 if let expectedHash=request["expected_hash"] as? String,expectedHash != before["text_sha256"] as? String {throw UIError(message:"Conversation changed before send; no action taken")}
 var all=descendants(try window())
 guard let input=all.first(where:{string(attr($0,"AXRole"))=="AXTextArea"}) else {throw UIError(message:"Conversation composer not found")}
 if !existingDraft {
  let changed=AXUIElementSetAttributeValue(input,"AXValue" as CFString,text as CFString)
  guard changed == .success else {throw UIError(message:"Native composer rejected AXValue (\(changed.rawValue)); no keyboard fallback was used")}
 }
 var sendButton:AXUIElement?
 for _ in 0..<20 {
  Thread.sleep(forTimeInterval:0.1);all=descendants(try window())
  sendButton=all.first{string(attr($0,"AXRole"))=="AXButton" && (string(attr($0,"AXHelp")).contains("发送") || string(attr($0,"AXHelp")).contains("Send") || ["arrow-right","arrow-up"].contains(label($0))) && (attr($0,"AXEnabled") as? Bool)==true}
  if sendButton != nil {break}
 }
 let after=try snapshot()
 // Expanding the composer can virtualize old message nodes. Recheck identity and
 // our exact draft instead of treating that layout change as a different chat.
 guard bound(after,expected,allowNew),!(after["busy"] as? Bool ?? true),after["input"] as? String == text else {throw UIError(message:"Session changed while preparing the message; text remains as a draft")}
 guard let button=sendButton else {throw UIError(message:"Send button did not enable; text remains as a draft")}
 guard AXUIElementPerformAction(button,kAXPressAction as CFString) == .success else {throw UIError(message:"Native Send action was not confirmed; inspect the existing composer before retrying")}
 return ["sent":true]
}
func cleanSource(_ request:[String:Any])throws {
 let state=try snapshot()
 guard let marker=request["from_marker"] as? String,marker.hasPrefix("[PCL:"),bound(state,marker,false),!(state["busy"] as? Bool ?? true),(state["input"] as? String ?? "").isEmpty else {throw UIError(message:"Conversation switch refused: source is not the owned idle chat, or contains a user draft")}
}
func selectChat(_ request:[String:Any])throws->[String:Any] {
 try cleanSource(request)
 guard let marker=request["session_marker"] as? String,marker.hasPrefix("[PCL:") else {throw UIError(message:"Missing target actor marker")}
 let all=descendants(try window())
 guard let button=all.first(where:{string(attr($0,"AXRole"))=="AXButton" && isConversationTab($0) && label($0).hasPrefix(marker)}) else {throw UIError(message:"Owned actor tab is no longer available")}
 guard AXUIElementPerformAction(button,kAXPressAction as CFString) == .success else {throw UIError(message:"Cannot select the owned actor tab")}
 for _ in 0..<30 {Thread.sleep(forTimeInterval:0.1);let state=try snapshot();if bound(state,marker,false){return state}}
 throw UIError(message:"Actor tab selection was not observed")
}
func newChat(_ request:[String:Any])throws->[String:Any] {
 try cleanSource(request)
 guard NSWorkspace.shared.runningApplications.contains(where:{$0.bundleIdentifier=="ai.perplexity.macv3"}),let connector=request["connector"] as? String else {throw UIError(message:"Missing Perplexity or connector")}
 // This main-window action creates a new tab and preserves the parent tab.
 // File > New conversation is a different action that opens a detached window.
 guard let newTab=descendants(try window()).first(where:{string(attr($0,"AXRole"))=="AXButton" && !isConversationTab($0) && ["新建会话","New thread","New Thread"].contains(label($0))}) else {throw UIError(message:"The main-window New conversation button is unavailable")}
 guard AXUIElementPerformAction(newTab,kAXPressAction as CFString) == .success else {throw UIError(message:"Cannot create the new actor tab")}
 var empty=false
 for _ in 0..<40 {Thread.sleep(forTimeInterval:0.1);let state=try snapshot();if (state["text"] as? String ?? "").isEmpty && (state["selected"] as? [String] ?? []).contains(where:{["新建会话","New thread","New Thread"].contains($0)}){empty=true;break}}
 guard empty else {throw UIError(message:"A fresh empty Perplexity tab was not observed")}
 var incognitoVerified=false
 if request["incognito"] as? Bool == true {
  // Separate account memory/search history as well as the visible thread context.
  for _ in 0..<2 {
   guard let toggle=descendants(try window()).first(where:{string(attr($0,"AXRole"))=="AXButton" && label($0)=="incognito-button"}) else {throw UIError(message:"The fresh actor's Incognito control is unavailable")}
   guard AXUIElementPerformAction(toggle,kAXPressAction as CFString) == .success else {throw UIError(message:"Cannot activate an Incognito actor")}
   for _ in 0..<12 {Thread.sleep(forTimeInterval:0.1);if descendants(try window()).contains(where:{label($0).contains("你已进入无痕模式") || label($0).contains("You're in Incognito")}){incognitoVerified=true;break}}
   if incognitoVerified {break}
  }
  guard incognitoVerified else {throw UIError(message:"Incognito activation was not observed; no actor prompt was sent")}
 }
 let all=descendants(try window())
 guard let more=all.first(where:{string(attr($0,"AXRole"))=="AXButton" && label($0)=="更多选项"}) else {throw UIError(message:"New-chat connector selector is unavailable")}
 guard AXUIElementPerformAction(more,kAXPressAction as CFString) == .success else {throw UIError(message:"Cannot open the connector selector")}
 for _ in 0..<30 {
  Thread.sleep(forTimeInterval:0.1)
  if let choice=descendants(try window()).first(where:{string(attr($0,"AXRole"))=="AXButton" && !isConversationTab($0) && label($0)==connector}) {
   guard AXUIElementPerformAction(choice,kAXPressAction as CFString) == .success else {throw UIError(message:"Cannot select the registered connector")}
   for _ in 0..<20 {Thread.sleep(forTimeInterval:0.1);var state=try snapshot();if (state["connectors"] as? [String] ?? []).contains(connector){state["incognito_verified"]=incognitoVerified;return state}}
   break
  }
 }
 throw UIError(message:"The intended connector was not observed in the new actor chat")
}
do {
 let mode=CommandLine.arguments.dropFirst().first ?? "snapshot"
 let result:[String:Any]
 if mode=="snapshot" {result=try snapshot()}
 else if ["send","new","select"].contains(mode) {guard let input=try JSONSerialization.jsonObject(with:FileHandle.standardInput.readDataToEndOfFile()) as? [String:Any] else {throw UIError(message:"Expected a JSON request on stdin")};result=try mode=="send" ? send(input):mode=="new" ? newChat(input):selectChat(input)}
 else {throw UIError(message:"Use snapshot, send, new or select")}
 print(String(data:try JSONSerialization.data(withJSONObject:result,options:[.sortedKeys]),encoding:.utf8)!)
}catch {let message=(error as? UIError)?.message ?? error.localizedDescription;print(String(data:try! JSONSerialization.data(withJSONObject:["error":message]),encoding:.utf8)!);exit(1)}
