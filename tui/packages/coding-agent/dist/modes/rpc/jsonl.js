import { StringDecoder } from "node:string_decoder";
export function serializeJsonLine(value) {
    return `${JSON.stringify(value)}\n`;
}
export function attachJsonlLineReader(stream, onLine) {
    const decoder = new StringDecoder("utf8");
    let buffer = "";
    const emitLine = (line) => {
        onLine(line.endsWith("\r") ? line.slice(0, -1) : line);
    };
    const onData = (chunk) => {
        buffer += typeof chunk === "string" ? chunk : decoder.write(chunk);
        while (true) {
            const newlineIndex = buffer.indexOf("\n");
            if (newlineIndex === -1) {
                return;
            }
            emitLine(buffer.slice(0, newlineIndex));
            buffer = buffer.slice(newlineIndex + 1);
        }
    };
    const onEnd = () => {
        buffer += decoder.end();
        if (buffer.length > 0) {
            emitLine(buffer);
            buffer = "";
        }
    };
    stream.on("data", onData);
    stream.on("end", onEnd);
    return () => {
        stream.off("data", onData);
        stream.off("end", onEnd);
    };
}
//# sourceMappingURL=jsonl.js.map