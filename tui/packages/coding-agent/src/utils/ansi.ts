function ansiRegex({ onlyFirst = false }: { onlyFirst?: boolean } = {}): RegExp {
	const ST = "(?:\\u0007|\\u001B\\u005C|\\u009C)";

	const osc = `(?:\\u001B\\][\\s\\S]*?${ST})`;

	const csi = "[\\u001B\\u009B][[\\]()#;?]*(?:\\d{1,4}(?:[;:]\\d{0,4})*)?[\\dA-PR-TZcf-nq-uy=><~]";

	const pattern = `${osc}|${csi}`;

	return new RegExp(pattern, onlyFirst ? undefined : "g");
}

const regex = ansiRegex();

export function stripAnsi(value: string): string {
	if (typeof value !== "string") {
		throw new TypeError(`Expected a \`string\`, got \`${typeof value}\``);
	}

	if (!value.includes("\u001B") && !value.includes("\u009B")) {
		return value;
	}

	return value.replace(regex, "");
}
