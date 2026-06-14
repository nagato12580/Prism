# prism/backend/app/utils/auto_migrate.py
from sqlalchemy import UniqueConstraint, inspect, text
from sqlalchemy.types import Integer, Boolean, Float, String

KNOWN_UNIQUE_CONSTRAINTS = {
    "uq_knowledge_topic_user_name",
    "uq_knowledge_file_user_topic_md5",
}


def auto_migrate(Base, engine) -> None:
    """对比 Base.metadata 与实际 schema，创建缺失的表和列。纯增量，不删除。"""
    inspector = inspect(engine)
    existing_tables = inspector.get_table_names()

    # 创建缺失的表
    for table_name, table_obj in Base.metadata.tables.items():
        if table_name not in existing_tables:
            print(f"[auto_migrate] 创建表: {table_name}")
            with engine.begin() as conn:
                table_obj.create(conn)
            continue

        # 表已存在，检查缺失的列
        existing_columns = {col["name"] for col in inspector.get_columns(table_name)}
        for col in table_obj.columns:
            if col.name not in existing_columns:
                col_type = str(col.type).compile(dialect=engine.dialect)
                print(f"[auto_migrate] 添加列: {table_name}.{col.name} {col_type}")
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
                    except Exception as e:
                        raise RuntimeError(
                            f"[auto_migrate] Failed to add column {table_name}.{col.name}: {e}"
                        ) from e

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
            print(f"[auto_migrate] 添加唯一约束 {table_name}.{constraint.name}")
            with engine.connect() as conn:
                try:
                    conn.execute(text(alter_sql))
                    conn.commit()
                except Exception as e:
                    raise RuntimeError(
                        f"[auto_migrate] Failed to add unique constraint {table_name}.{constraint.name}: {e}"
                    ) from e


def _infer_default(col):
    """根据类型推断 ADD COLUMN 的默认值（MySQL 要求 NOT NULL 列有默认值）。"""
    col_type = col.type
    if isinstance(col_type, (Integer, Boolean)):
        return " DEFAULT 0"
    if isinstance(col_type, Float):
        return " DEFAULT 0"
    if isinstance(col_type, String):
        return " DEFAULT ''"
    # Text/JSON 等大字段不加默认值（MySQL 限制）
    return ""
