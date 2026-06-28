# prism/backend/app/utils/auto_migrate.py
from sqlalchemy import UniqueConstraint, inspect, text
from sqlalchemy.sql.sqltypes import Text
from sqlalchemy.types import Boolean, Float, Integer, String

KNOWN_UNIQUE_CONSTRAINTS = {
    "uq_knowledge_topic_user_name",
    "uq_knowledge_file_user_topic_md5",
    "uq_pku_source_normalized",
    "uq_pku_ckp_relation",
    "uq_pku_relation",
    "uq_ckp_relation",
    "uq_entity_user_type_key",
    "uq_entity_alias_key",
    "uq_entity_mention_source_surface",
    "uq_entity_relation_evidence",
}


def auto_migrate(Base, engine) -> None:
    """Incrementally create missing tables, columns, and known constraints."""
    inspector = inspect(engine)
    existing_tables = inspector.get_table_names()

    if "knowledge_draft" in existing_tables and "personal_asset_unit" not in existing_tables:
        print("[auto_migrate] Rename table: knowledge_draft -> personal_asset_unit")
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE `knowledge_draft` RENAME TO `personal_asset_unit`"))
        inspector = inspect(engine)
        existing_tables = inspector.get_table_names()

    for table_name, table_obj in Base.metadata.tables.items():
        if table_name not in existing_tables:
            print(f"[auto_migrate] Create table: {table_name}")
            with engine.begin() as conn:
                table_obj.create(conn)
            continue

        inspected_columns = inspector.get_columns(table_name)
        existing_columns = {col["name"] for col in inspected_columns}
        existing_column_map = {col["name"]: col for col in inspected_columns}
        for col in table_obj.columns:
            if col.name in existing_columns:
                _upgrade_column_type_if_needed(engine, table_name, col, existing_column_map[col.name])
                continue
            col_type = col.type.compile(dialect=engine.dialect)
            print(f"[auto_migrate] Add column: {table_name}.{col.name} {col_type}")
            default = _infer_default(col)
            alter_sql = (
                f"ALTER TABLE `{table_name}` "
                f"ADD COLUMN `{col.name}` {col_type}{default}"
            )
            if col.comment:
                safe_comment = col.comment.replace("'", "''")
                alter_sql += f" COMMENT '{safe_comment}'"
            with engine.connect() as conn:
                try:
                    conn.execute(text(alter_sql))
                    conn.commit()
                except Exception as exc:
                    raise RuntimeError(
                        f"[auto_migrate] Failed to add column {table_name}.{col.name}: {exc}"
                    ) from exc

        existing_unique_names = {
            item.get("name")
            for item in inspector.get_unique_constraints(table_name)
            if item.get("name")
        }
        for constraint in table_obj.constraints:
            if not isinstance(constraint, UniqueConstraint):
                continue
            if constraint.name not in KNOWN_UNIQUE_CONSTRAINTS:
                continue
            if constraint.name in existing_unique_names:
                continue
            columns = [f"`{column.name}`" for column in constraint.columns]
            if not columns:
                continue
            alter_sql = (
                f"ALTER TABLE `{table_name}` "
                f"ADD CONSTRAINT `{constraint.name}` UNIQUE ({', '.join(columns)})"
            )
            print(f"[auto_migrate] Add unique constraint: {table_name}.{constraint.name}")
            with engine.connect() as conn:
                try:
                    conn.execute(text(alter_sql))
                    conn.commit()
                except Exception as exc:
                    print(f"[auto_migrate] Skip constraint {constraint.name}: {exc}")


def _infer_default(col):
    """Infer ADD COLUMN defaults for non-nullable MySQL columns."""
    col_type = col.type
    if isinstance(col_type, (Integer, Boolean)):
        return " DEFAULT 0"
    if isinstance(col_type, Float):
        return " DEFAULT 0"
    if isinstance(col_type, String) and not isinstance(col_type, Text):
        return " DEFAULT ''"
    return ""


def _upgrade_column_type_if_needed(engine, table_name: str, model_col, existing_col: dict) -> None:
    model_type = model_col.type
    target_type = model_type.compile(dialect=engine.dialect)
    if target_type.lower() != "mediumtext":
        return

    existing_type = existing_col.get("type")
    existing_type_name = existing_type.compile(dialect=engine.dialect).lower() if existing_type is not None else ""
    if existing_type_name == "mediumtext":
        return

    alter_sql = f"ALTER TABLE `{table_name}` MODIFY COLUMN `{model_col.name}` {target_type}"
    if model_col.comment:
        safe_comment = model_col.comment.replace("'", "''")
        alter_sql += f" COMMENT '{safe_comment}'"

    print(f"[auto_migrate] Modify column: {table_name}.{model_col.name} {target_type}")
    with engine.connect() as conn:
        try:
            conn.execute(text(alter_sql))
            conn.commit()
        except Exception as exc:
            raise RuntimeError(
                f"[auto_migrate] Failed to modify column {table_name}.{model_col.name}: {exc}"
            ) from exc
