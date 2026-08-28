# Browser Control health and recovery

Use this reference whenever a task needs the user's existing Chrome profile/session or when Chrome Browser Control appears unavailable.

## Core distinction

Do not collapse Browser Control into generic browser automation. Keep these layers separate:

```text
browser_host_health:
  chrome_running
  extension_installed
  extension_enabled
  native_host_valid

browser_session_health:
  browser_capability_available
  chrome_binding_available
  current_session_connected
```

A healthy local Chrome bridge does not prove that the current ChatGPT conversation has a callable Browser executor. Likewise, an unavailable Browser tool in one conversation does not prove that the user's local Chrome installation is broken.

Use stable internal states where practical:

- `CHROME_NOT_RUNNING`
- `EXTENSION_NOT_INSTALLED`
- `EXTENSION_DISABLED`
- `NATIVE_HOST_MISSING`
- `NATIVE_HOST_INVALID`
- `BRIDGE_HEALTHY`
- `SESSION_BROWSER_CAPABILITY_MISSING`
- `READY`

## Health-check order

For an explicitly authorized `local_chrome` Browser task, check in this order:

1. Confirm Chrome is running when the task requires the user's current Chrome session.
2. Confirm the ChatGPT Chrome integration/extension is installed and enabled through supported host diagnostics when available.
3. Confirm the native messaging host registration is present and valid.
4. Only after host health is good, confirm that the current conversation actually exposes a supported Browser/Chrome executor.
5. Start the Browser task only when both host health and session health are ready.

When the bundled diagnostics exist, prefer them over ad-hoc filesystem probing. Typical helpers under the ChatGPT bundled Chrome plugin include:

```text
scripts/chrome-is-running.js --browser chrome --check
scripts/installed-browsers.js --json
scripts/check-extension-installed.js --browser chrome --json
scripts/check-native-host-manifest.js --browser chrome --json
```

Treat these paths as host-version dependent. If the supported diagnostics are not exposed, report the missing diagnostic surface rather than guessing private implementation details.

## Native host recovery

If the extension exists but the native messaging host is missing or invalid, use the product recovery path first:

```text
ChatGPT / Codex
-> Settings
-> Computer use
-> Google Chrome
-> Manage / Reconnect
```

After the user completes that flow, re-run the host health check. Do not ask the user to reinstall Chrome first, do not hand-create `com.openai.codexextension.json`, and do not modify internal browser-use sockets.

A known macOS manifest location is:

```text
~/Library/Application Support/Google/Chrome/NativeMessagingHosts/com.openai.codexextension.json
```

Use it only for supported diagnostics. Do not synthesize or repair the manifest manually unless OpenAI provides an explicit supported repair interface.

## Session capability recovery

If Chrome, extension, and native host are healthy but the current conversation still has no supported Browser executor, classify the problem as:

```text
SESSION_BROWSER_CAPABILITY_MISSING
```

Report the distinction explicitly, for example:

```text
Local Chrome bridge healthy.
Current conversation does not have Chrome Browser capability attached.
```

Then recommend starting a Browser-capable conversation or re-enabling/selecting Chrome on the current ChatGPT surface. Do not repeat local Chrome repair steps when host health is already healthy.

## Forbidden substitutions

Do not claim Browser Control success from any of the following:

- RDC -> AppleScript -> `tell application "Google Chrome"` -> `execute javascript`;
- generic screenshot/mouse/keyboard automation;
- direct attachment to `/tmp/codex-browser-use/*.sock` or another internal Browser/Codex socket;
- successful tab creation/query through an unrelated automation path;
- ordinary web search used as a substitute for Cloud Browser execution.

RDC may be used for narrowly scoped, explicitly authorized host diagnostics or user-visible setup navigation. It is not a Browser Control executor. If the user explicitly requests a nonstandard RDC/AppleScript Chrome automation path after the Browser limitation is disclosed, treat that as a separate computer-automation action and label the evidence accordingly; never use it as proof that Browser capability is attached.

## Verification rule

A Browser smoke test counts as `READY` only when it runs through the supported Browser/Chrome execution surface attached to the current conversation. Verify at least one harmless real action such as opening a test page and reading a page result through that executor.

Do not mark Cloud Browser routing, background/silent Chrome execution, locked-Mac behavior, or logged-in Chrome behavior as verified merely because generic Chrome automation works. Those capabilities require their own dedicated tests.
