export function getCortexUserAgent(version: string): string {
	const runtime = process.versions.bun ? `bun/${process.versions.bun}` : `node/${process.version}`;
	return `cortex/${version} (${process.platform}; ${runtime}; ${process.arch})`;
}
