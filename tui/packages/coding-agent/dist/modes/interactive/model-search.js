export function getModelSearchText(item) {
    const { id, provider } = item;
    const name = item.name ? ` ${item.name}` : "";
    return `${id} ${provider} ${provider}/${id} ${provider} ${id}${name}`;
}
export function getModelSelectorSearchText(item) {
    const { id, provider } = item;
    const name = item.name ? ` ${item.name}` : "";
    return `${provider} ${provider}/${id} ${provider} ${id}${name}`;
}
//# sourceMappingURL=model-search.js.map