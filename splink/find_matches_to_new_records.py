from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .linker import Linker
    from .splink_dataframe import SplinkDataFrame


def add_unique_id_and_source_dataset_cols_if_needed(
    linker: "Linker", new_records_df: "SplinkDataFrame"
):
    cols = new_records_df.columns

    sds_col, _ = linker._settings_obj._source_dataset_col

    sds_sel_sql = ""
    if sds_col not in cols:
        sds_sel_sql = f", 'new_record' as {sds_col}"

    uid_col = linker._settings_obj._unique_id_column_name
    if uid_col not in cols:
        uid_sel_sql = f", 'id' as {uid_col}, 'new_record' as {sds_col}"

    sql = f"""
        select * {sds_sel_sql} {uid_sel_sql}
        from  __splink__df_new_records_with_tf_before_uid_fix
        """
    linker._enqueue_sql(sql, "__splink__df_new_records_with_tf")
