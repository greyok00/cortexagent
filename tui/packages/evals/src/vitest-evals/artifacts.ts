import { createHash } from "node:crypto";
import { mkdir, writeFile } from "node:fs/promises";
import { basename, join, relative } from "node:path";
import {
	type RunnerTestCase,
	recordArtifact,
	type TestArtifact,
	type TestArtifactBase,
	type TestAttachment,
} from "vitest";
import type { HarnessRun } from "vitest-evals/harness";

export const CORTEX_SESSION_SNAPSHOT_ARTIFACT = "piSessionJsonl";

const evalSessionArtifactKey = Symbol("cortex-evals-session-artifact");
const evalSourceArtifactKey = Symbol("cortex-evals-source-artifact");

interface CortexSessionAttachment extends TestAttachment {
	name: "session.jsonl";
	contentType: "application/jsonl";
	body: string;
	bodyEncoding: "utf-8";
}

export interface SourceAttachment extends TestAttachment {
	name: string;
	contentType: string;
	body: string;
	bodyEncoding: "utf-8";
}

interface CortexSessionArtifact extends TestArtifactBase {
	type: "@cortexagent/evals:session";
	runId: string;
	attachments: [CortexSessionAttachment] | [];
}

interface SourceArtifact extends TestArtifactBase {
	type: "@cortexagent/evals:source";
	runId: string;
	attachments: [SourceAttachment] | [];
}

declare module "vitest" {
	interface TestArtifactRegistry {
		[evalSessionArtifactKey]: CortexSessionArtifact;
		[evalSourceArtifactKey]: SourceArtifact;
	}
}

export async function recordEvalSessionArtifact(
	task: Readonly<RunnerTestCase>,
	run: Pick<HarnessRun, "artifacts">,
): Promise<void> {
	const runId = run.artifacts?.runId;
	const session = run.artifacts?.[CORTEX_SESSION_SNAPSHOT_ARTIFACT];
	if (session === undefined) return;
	if (typeof runId !== "string" || typeof session !== "string") {
		throw new TypeError("Cortex eval session artifact metadata is invalid.");
	}
	await recordArtifact(task, {
		type: "@cortexagent/evals:session",
		runId,
		attachments: [
			{
				name: "session.jsonl",
				contentType: "application/jsonl",
				body: session,
				bodyEncoding: "utf-8",
			},
		],
	});
}

export async function recordEvalSourceArtifact(
	task: Readonly<RunnerTestCase>,
	runId: string,
	attachment: SourceAttachment,
): Promise<void> {
	await recordArtifact(task, {
		type: "@cortexagent/evals:source",
		runId,
		attachments: [attachment],
	});
}

export async function persistEvalArtifactReferences(
	artifacts: ReadonlyArray<TestArtifact>,
	runId: string,
	artifactDirectory: string,
): Promise<Array<{ name: string; path: string }>> {
	const references: Array<{ name: string; path: string }> = [];
	for (const artifact of artifacts) {
		if (
			(artifact.type !== "@cortexagent/evals:session" && artifact.type !== "@cortexagent/evals:source") ||
			artifact.runId !== runId
		) {
			continue;
		}
		const category = artifact.type === "@cortexagent/evals:session" ? "sessions" : "sources";
		for (const attachment of artifact.attachments) {
			const name = basename(attachment.name);
			if (name !== attachment.name) throw new TypeError(`Invalid eval artifact name: ${attachment.name}`);
			const directory = join(artifactDirectory, category, createHash("sha256").update(runId).digest("hex"));
			await mkdir(directory, { recursive: true, mode: 0o700 });
			const path = join(directory, name);
			await writeFile(path, attachment.body, { encoding: "utf8", mode: 0o600 });
			references.push({ name, path: relative(artifactDirectory, path) });
		}
	}
	return references;
}
