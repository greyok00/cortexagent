export class SqlQuery {
    queryText;
    params;
    constructor(queryText, params = []) {
        this.queryText = queryText;
        this.params = params;
    }
    exec(db) {
        if (this.params.length > 0)
            throw new TypeError("SQLite exec queries cannot have parameters");
        db.exec(this.queryText);
    }
    run(db) {
        return db.prepare(this.queryText).run(...this.params);
    }
    get(db) {
        return db.prepare(this.queryText).get(...this.params);
    }
    all(db) {
        return db.prepare(this.queryText).all(...this.params);
    }
    iterate(db) {
        return db.prepare(this.queryText).iterate(...this.params);
    }
}
export function sql(strings, ...values) {
    let queryText = strings[0] ?? "";
    const params = [];
    for (let index = 0; index < values.length; index++) {
        const value = values[index];
        if (value instanceof SqlQuery) {
            queryText += value.queryText;
            params.push(...value.params);
        }
        else {
            queryText += "?";
            params.push(value);
        }
        queryText += strings[index + 1] ?? "";
    }
    return new SqlQuery(queryText, params);
}
export function joinSqlFragments(fragments, separator) {
    let queryText = "";
    const params = [];
    for (let index = 0; index < fragments.length; index++) {
        if (index > 0)
            queryText += separator;
        const fragment = fragments[index];
        queryText += fragment.queryText;
        params.push(...fragment.params);
    }
    return new SqlQuery(queryText, params);
}
//# sourceMappingURL=sql.js.map