import { describe, expect, test, vi } from "vitest";

function createTinyBmp1x1Red24bpp(): Uint8Array {
	const buffer = Buffer.alloc(58);

	buffer.write("BM", 0, "ascii");
	buffer.writeUInt32LE(buffer.length, 2);
	buffer.writeUInt16LE(0, 6);
	buffer.writeUInt16LE(0, 8);
	buffer.writeUInt32LE(54, 10);

	buffer.writeUInt32LE(40, 14);
	buffer.writeInt32LE(1, 18);
	buffer.writeInt32LE(1, 22);
	buffer.writeUInt16LE(1, 26);
	buffer.writeUInt16LE(24, 28);
	buffer.writeUInt32LE(0, 30);
	buffer.writeUInt32LE(4, 34);
	buffer.writeInt32LE(0, 38);
	buffer.writeInt32LE(0, 42);
	buffer.writeUInt32LE(0, 46);
	buffer.writeUInt32LE(0, 50);

	buffer[54] = 0x00;
	buffer[55] = 0x00;
	buffer[56] = 0xff;
	buffer[57] = 0x00;

	return new Uint8Array(buffer);
}

vi.mock("child_process", async () => {
	const actual = await vi.importActual<typeof import("child_process")>("child_process");
	return {
		...actual,
		spawnSync: vi.fn((command: string, args: string[]) => {
			if (command === "wl-paste" && args.includes("--list-types")) {
				return { status: 0, stdout: Buffer.from("image/bmp\n"), error: null };
			}
			if (command === "wl-paste" && args.includes("image/bmp")) {
				return { status: 0, stdout: Buffer.from(createTinyBmp1x1Red24bpp()), error: null };
			}
			return { status: 1, stdout: Buffer.alloc(0), error: null };
		}),
	};
});

vi.mock("@mariozechner/clipboard", () => ({
	default: {
		hasImage: vi.fn(() => false),
		getImageBinary: vi.fn(() => Promise.resolve(null)),
	},
}));

describe("readClipboardImage BMP conversion", () => {
	test("converts BMP to PNG on Wayland/WSLg", async () => {
		const { readClipboardImage } = await import("../src/utils/clipboard-image.ts");

		const image = await readClipboardImage({
			env: { WAYLAND_DISPLAY: "wayland-0" },
			platform: "linux",
		});

		expect(image).not.toBeNull();
		expect(image!.mimeType).toBe("image/png");

		expect(image!.bytes[0]).toBe(0x89);
		expect(image!.bytes[1]).toBe(0x50);
		expect(image!.bytes[2]).toBe(0x4e);
		expect(image!.bytes[3]).toBe(0x47);
	});
});
