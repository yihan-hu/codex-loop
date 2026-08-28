# Local macOS GUI computer use

Use this reference when `interaction_target=local_mac_gui`. This path is for explicitly authorized native macOS UI interaction through RDC. It is separate from Browser Control and must never be used as evidence that a Browser/Chrome executor is attached.

## Capability contract

Require all of the following before acting:

- explicit computer-use authorization for the current task;
- an online RDC device;
- macOS Accessibility permission for the host process when Accessibility inspection or UI actions are needed;
- any additional host permission genuinely required by the chosen observation path, such as Screen Recording for screenshot-based targeting.

Do not enter Local repository-development mode merely because RDC is used for GUI interaction. Interaction-only use must not inspect or mutate a local checkout while `workspace_mode=web`.

## Targeting order

Use the narrowest, most stable control surface available:

1. Prefer a structured application API when it can perform the requested action and return observable state.
2. Otherwise inspect the target application's Accessibility tree and prefer stable `AXRole`, `AXIdentifier`, label, help text, or other semantic attributes.
3. When a real mouse click is required, derive the click point from the target Accessibility element's current position and size, then emit the mouse event through the supported host/macOS event path such as CoreGraphics.
4. Use screenshot-derived or manually inferred coordinates only when semantic UI targeting is unavailable. Keep the captured scope minimal and verify the result independently.

Do not hard-code screen coordinates into reusable behavior when the element geometry can be resolved at runtime. Window position, display scale, localization, and application layout can change.

## Mouse and keyboard discipline

For coordinate mouse interaction:

- verify the target application/window immediately before the action;
- prefer the center of the resolved target element unless the control requires another hit point;
- record the original mouse position when practical and restore it after an ephemeral test/action;
- avoid unnecessary cursor movement and window activation;
- do not treat a successful mouse-event dispatch as proof that the target action occurred.

Avoid global keystrokes when a direct element action or mouse click can be used. If keyboard input is necessary, activate the intended application, verify its frontmost/focused window state, perform the minimum input, and read back target-app state immediately. A keystroke landing in another application is a routing failure, not an application failure.

## Verification and cleanup

After every meaningful GUI action, independently observe the target application's state through Accessibility, a structured application API, or another supported readback path. Prefer semantic state over visual assumptions.

For temporary smoke tests:

- record the pre-test foreground application and mouse position when practical;
- create only the minimum temporary window/tab/application state;
- verify the expected result;
- close only artifacts created by the test;
- restore the mouse position and foreground application when doing so will not disturb user work.

## Verified macOS smoke test

This capability was verified on macOS with Calculator using the following pattern:

1. Inspect Calculator's Accessibility tree.
2. Resolve the `AXIdentifier` values `AllClear`, `Two`, `Add`, and `Equals` plus each element's current geometry.
3. Derive element centers dynamically.
4. Emit real CoreGraphics mouse move/down/up events for `AC -> 2 -> + -> 2 -> =`.
5. Read Calculator's Accessibility state after the click sequence.
6. Confirm the previous-expression view contains `2+2` and the current result/input view contains `4`.
7. Restore transient UI state.

The verified fact is the control pattern, not those specific screen coordinates. Re-resolve geometry on every real task.

## Browser boundary

Do not use `local_mac_gui` as a silent replacement for `local_chrome` Browser Control. If the official Browser executor is missing, report that Browser capability failure first. Only use generic GUI/browser automation when the user explicitly requests that separate nonstandard path after the limitation is disclosed; label its evidence as local GUI computer automation, not Browser Control.

Do not attach to private Browser/Codex sockets or use this path to bypass Browser safety or confirmation semantics.

## Unverified behavior

Do not claim the following until separately tested on the active host/runtime:

- silent/background execution without stealing focus;
- reliable operation while the Mac is locked;
- screenshot-based control without Screen Recording permission;
- cross-display or unusual display-scaling behavior;
- equivalence with host-native Computer Use or Browser Control safety semantics.
