# prism/backend/app/utils/auto_migrate.py
from sqlalchemy import inspect, text
from sqlalchemy.types import Integer, Boolean, Float, String


def auto_migrate(Base, engine) -> None:
    """对比 Base.metadata 与实际 schema，创建缺失的表和列。纯增量，不删除。"""
    inspector = inspect(engine)
    existing_tables = inspector.get_table_names()

    # 创建缺失的表
    for table_name, table_obj in Base.metadata.tables.items():
        if table_name not in existing_tables:
            print(f"[auto_migrate] 创建表: {table_name}")
            table_obj.create(bind=engine)
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
                    alter_sql += f" COMMENT '{col.comment}'"
                with engine.connect() as conn:
                    conn.execute(text(alter_sql))
                    conn.commit()


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
