import type { ExtensionAPI } from "@cortexagent/coding-agent";
import { DoomOverlayComponent } from "./doom-component.ts";
import { DoomEngine } from "./doom-engine.ts";
import { ensureWadFile } from "./wad-finder.ts";

let activeEngine: DoomEngine | null = null;
let activeWadPath: string | null = null;

export default function (cortex: ExtensionAPI) {
	cortex.registerCommand("doom-overlay", {
		description: "Play DOOM as an overlay. Q to pause and exit.",

		handler: async (args, ctx) => {
			if (ctx.mode !== "tui") {
				ctx.ui.notify("DOOM requires interactive mode", "error");
				return;
			}

			ctx.ui.notify("Loading DOOM...", "info");
			const wad = args?.trim() ? args.trim() : await ensureWadFile();

			if (!wad) {
				ctx.ui.notify("Failed to download DOOM WAD file. Check your internet connection.", "error");
				return;
			}

			try {
				let isResume = false;
				if (activeEngine && activeWadPath === wad) {
					ctx.ui.notify("Resuming DOOM...", "info");
					isResume = true;
				} else {
					ctx.ui.notify(`Loading DOOM from ${wad}...`, "info");
					activeEngine = new DoomEngine(wad);
					await activeEngine.init();
					activeWadPath = wad;
				}

				await ctx.ui.custom(
					(tui, _theme, _keybindings, done) => {
						return new DoomOverlayComponent(tui, activeEngine!, () => done(undefined), isResume);
					},
					{
						overlay: true,
						overlayOptions: {
							width: "75%",
							maxHeight: "95%",
							anchor: "center",
							margin: { top: 1 },
						},
					},
				);
			} catch (error) {
				ctx.ui.notify(`Failed to load DOOM: ${error}`, "error");
				activeEngine = null;
				activeWadPath = null;
			}
		},
	});
}
