"""9kg.58: refine existing guards without replacing their other protections or privileges."""


def refine(schema_editor, name, alias, timestamp, *, reverse=False):
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(
            "SELECT pg_get_functiondef(p.oid) FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace"
            " WHERE n.nspname = 'public' AND p.proname = %s AND p.pronargs = 0",
            [name],
        )
        rows = cursor.fetchall()
    if len(rows) != 1:
        raise RuntimeError(f"expected one existing transaction guard: {name}")
    definition = rows[0][0]
    old = f"AND {alias}.created_txid = pg_current_xact_id()::text::bigint"
    fresh = f" AND {alias}.{timestamp} >= pg_catalog.transaction_timestamp()"
    if definition.count(old) != 1 or definition.count(fresh) != int(reverse):
        raise RuntimeError(f"unexpected transaction guard definition: {name}")
    before, after = (old + fresh, old) if reverse else (old, old + fresh)
    # CREATE OR REPLACE preserves owner, grants, trigger identity and the erasure branch.
    # No table, historical timestamp or transaction marker is rewritten.
    schema_editor.execute(definition.replace(before, after, 1), params=None)
