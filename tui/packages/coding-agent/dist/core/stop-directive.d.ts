/**
 * Detects user input that is purely a stop order ("STOP", "stop it now",
 * "cancel that please"). Only unambiguous directives match: every word must
 * be a stop verb or a filler word. Messages that merely CONTAIN a stop word
 * ("stop the scan and list the results") still reach the model as steering,
 * where the terminal-abort check and churn guards in the agent loop provide
 * the backstop.
 *
 * Exception: a mixed message whose FINAL sentence is a pure stop order is
 * still a stop order ("...WHAT DID I JUST SAY. STOP IT NOW"). During the
 * 2026-09-23 runaway incident such messages were queued as steering and the
 * run kept going while the user was shouting stop.
 */
export declare function isStopDirective(text: string): boolean;
//# sourceMappingURL=stop-directive.d.ts.map