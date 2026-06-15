# prism/backend/app/utils/auto_migrate.py
from sqlalchemy import UniqueConstraint, inspect, text
from sqlalchemy.sql.sqltypes import Text
from sqlalchemy.types import Boolean, Float, Integer, String

KNOWN_UNIQUE_CONSTRAINTS = {
    "uq_knowledge_topic_user_name",
    "uq_knowledge_file_user_topic_md5",
}


def auto_migrate(Base, engine) -> None:
    """Incrementally create missing tables, columns, and known constraints."""
    inspector = inspect(engine)
    existing_tables = inspector.get_table_names()

    for table_name, table_obj in Base.metadata.tables.items():
        if table_name not in existing_tables:
            print(f"[auto_migrate] Create table: {table_name}")
            with engine.begin() as conn:
                table_obj.create(conn)
            continue

        existing_columns = {col["name"] for col in inspector.get_columns(table_name)}
        for col in table_obj.columns:
            if col.name in existing_columns:
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
