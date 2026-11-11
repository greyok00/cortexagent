import { spawn as nodeSpawn, spawnSync as nodeSpawnSync, } from "node:child_process";
import crossSpawn from "cross-spawn";
const EXIT_STDIO_GRACE_MS = 100;
export function spawnProcess(command, args, options) {
    return process.platform === "win32" ? crossSpawn(command, args, options) : nodeSpawn(command, args, options);
}
export function spawnProcessSync(command, args, options) {
    return process.platform === "win32"
        ? crossSpawn.sync(command, args, options)
        : nodeSpawnSync(command, args, options);
}
export function waitForChildProcess(child) {
    return new Promise((resolve, reject) => {
        let settled = false;
        let exited = false;
        let exitCode = null;
        let postExitTimer;
        let stdoutEnded = child.stdout === null;
        let stderrEnded = child.stderr === null;
        const cleanup = () => {
            if (postExitTimer) {
                clearTimeout(postExitTimer);
                postExitTimer = undefined;
            }
            child.removeListener("error", onError);
            child.removeListener("exit", onExit);
            child.removeListener("close", onClose);
            child.stdout?.removeListener("end", onStdoutEnd);
            child.stderr?.removeListener("end", onStderrEnd);
            child.stdout?.removeListener("data", onData);
            child.stderr?.removeListener("data", onData);
        };
        const finalize = (code) => {
            if (settled)
                return;
            settled = true;
            cleanup();
            child.stdout?.destroy();
            child.stderr?.destroy();
            resolve(code);
        };
        const maybeFinalizeAfterExit = () => {
            if (!exited || settled)
                return;
            if (stdoutEnded && stderrEnded) {
                finalize(exitCode);
            }
        };
        const armIdleTimer = () => {
            if (postExitTimer)
                clearTimeout(postExitTimer);
            postExitTimer = setTimeout(() => finalize(exitCode), EXIT_STDIO_GRACE_MS);
        };
        const onData = () => {
            if (exited && !settled)
                armIdleTimer();
        };
        const onStdoutEnd = () => {
            stdoutEnded = true;
            maybeFinalizeAfterExit();
        };
        const onStderrEnd = () => {
            stderrEnded = true;
            maybeFinalizeAfterExit();
        };
        const onError = (err) => {
            if (settled)
                return;
            settled = true;
            cleanup();
            reject(err);
        };
        const onExit = (code) => {
            exited = true;
            exitCode = code;
            maybeFinalizeAfterExit();
            if (!settled) {
                armIdleTimer();
            }
        };
        const onClose = (code) => {
            finalize(code);
        };
        child.stdout?.once("end", onStdoutEnd);
        child.stderr?.once("end", onStderrEnd);
        child.stdout?.on("data", onData);
        child.stderr?.on("data", onData);
        child.once("error", onError);
        child.once("exit", onExit);
        child.once("close", onClose);
    });
}
//# sourceMappingURL=child-process.js.map