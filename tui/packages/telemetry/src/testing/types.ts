import type { TelemetryContext } from "../index.ts";
import type { RecordedTelemetrySpan } from "../memory.ts";

export interface TelemetryAdapterFixture extends AsyncDisposable {
	readonly context: TelemetryContext;
	getSpans(): Promise<readonly RecordedTelemetrySpan[]>;
}

export type TelemetryAdapterFixtureFactory = () => Promise<TelemetryAdapterFixture>;

export interface TelemetryAdapterConformanceCase {
	readonly group: string;
	readonly name: string;
	run(): Promise<void>;
}
