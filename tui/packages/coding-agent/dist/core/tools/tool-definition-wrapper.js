export function wrapToolDefinition(definition, ctxFactory) {
    return {
        name: definition.name,
        label: definition.label,
        description: definition.description,
        parameters: definition.parameters,
        constrainedSampling: definition.constrainedSampling,
        prepareArguments: definition.prepareArguments,
        executionMode: definition.executionMode,
        execute: (toolCallId, params, signal, onUpdate, ctx) => definition.execute(toolCallId, params, signal, onUpdate, ctx ?? ctxFactory?.()),
    };
}
export function wrapToolDefinitions(definitions, ctxFactory) {
    return definitions.map((definition) => wrapToolDefinition(definition, ctxFactory));
}
export function createToolDefinitionFromAgentTool(tool) {
    return {
        name: tool.name,
        label: tool.label,
        description: tool.description,
        parameters: tool.parameters,
        constrainedSampling: tool.constrainedSampling,
        prepareArguments: tool.prepareArguments,
        executionMode: tool.executionMode,
        execute: async (toolCallId, params, signal, onUpdate) => tool.execute(toolCallId, params, signal, onUpdate),
    };
}
//# sourceMappingURL=tool-definition-wrapper.js.map