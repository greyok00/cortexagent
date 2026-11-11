import { wrapToolDefinition } from "../tools/tool-definition-wrapper.js";
export function wrapRegisteredTool(registeredTool, runner) {
    const tool = wrapToolDefinition(registeredTool.definition, () => runner.createContext());
    const execute = tool.execute;
    return {
        ...tool,
        execute: async (toolCallId, params, signal, onUpdate) => {
            const activeBefore = runner.getActiveTools();
            const result = await execute(toolCallId, params, signal, onUpdate);
            const activeAfter = runner.getActiveTools();
            if (!activeBefore.every((name) => activeAfter.includes(name)))
                return result;
            const beforeNames = new Set(activeBefore);
            const addedToolNames = activeAfter.filter((name) => !beforeNames.has(name));
            if (addedToolNames.length === 0)
                return result;
            return {
                ...result,
                addedToolNames: [...new Set([...(result.addedToolNames ?? []), ...addedToolNames])],
            };
        },
    };
}
export function wrapRegisteredTools(registeredTools, runner) {
    return registeredTools.map((tool) => wrapRegisteredTool(tool, runner));
}
//# sourceMappingURL=wrapper.js.map