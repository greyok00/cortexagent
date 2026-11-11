import { spawn } from "node:child_process";
export function openBrowser(target) {
    const [cmd, args] = process.platform === "darwin"
        ? ["open", [target]]
        : process.platform === "win32"
            ? ["rundll32", ["url.dll,FileProtocolHandler", target]]
            : ["xdg-open", [target]];
    spawn(cmd, args, { stdio: "ignore", detached: true })
        .on("error", () => { })
        .unref();
}
//# sourceMappingURL=open-browser.js.map