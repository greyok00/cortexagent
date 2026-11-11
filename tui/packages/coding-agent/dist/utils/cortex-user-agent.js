export function getCortexUserAgent(version) {
    const runtime = process.versions.bun ? `bun/${process.versions.bun}` : `node/${process.version}`;
    return `cortex/${version} (${process.platform}; ${runtime}; ${process.arch})`;
}
//# sourceMappingURL=cortex-user-agent.js.map