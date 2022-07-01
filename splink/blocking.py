from typing import TYPE_CHECKING
import logging

from .unique_id_concat import _composite_unique_id_from_nodes_sql

logger = logging.getLogger(__name__)

# https://stackoverflow.com/questions/39740632/python-type-hinting-without-cyclic-imports
if TYPE_CHECKING:
    from .linker import Linker


class BlockingRule:
    def __init__(
        self,
        blocking_rule,
        previous_rules,
    ):
        self.blocking_rule = blocking_rule
        self.previous_rules = previous_rules.copy()
        self.match_key = len(previous_rules)

    def _add_salt_to_blocking_rule(self, salting):

        salt_to_sprinkle = []
        rule = self.blocking_rule

        if salting > 1:
            for n in range(1, salting+1):
                salt = f"l.__splink_salt = {n}"
                salting_rule = f"{rule} and {salt}"
                salt_to_sprinkle.append(salting_rule)
        else:
            salt_to_sprinkle = rule

        self.salt = salt_to_sprinkle


def _sql_gen_and_not_previous_rules(rule: BlockingRule):

    previous_rules = rule.previous_rules
    if previous_rules:
        # Note the coalesce function is important here - otherwise
        # you filter out any records with nulls in the previous rules
        # meaning these comparisons get lost
        or_clauses = [f"coalesce(({r}), false)" for r in previous_rules]
        previous_rules = " OR ".join(or_clauses)
        return f"AND NOT ({previous_rules})"
    else:
        return ""


def _sql_gen_where_condition(link_type, unique_id_cols):

    id_expr_l = _composite_unique_id_from_nodes_sql(unique_id_cols, "l")
    id_expr_r = _composite_unique_id_from_nodes_sql(unique_id_cols, "r")

    if link_type in ("two_dataset_link_only", "self_link"):
        where_condition = " where 1=1 "
    elif link_type in ["link_and_dedupe", "dedupe_only"]:
        where_condition = f"where {id_expr_l} < {id_expr_r}"
    elif link_type == "link_only":
        source_dataset_col = unique_id_cols[0]
        where_condition = (
            f"where {id_expr_l} < {id_expr_r} "
            f"and l.{source_dataset_col.name()} != r.{source_dataset_col.name()}"
        )

    return where_condition


def block_using_rules_sql(linker: "Linker"):
    """Use the blocking rules specified in the linker's settings object to
    generate a SQL statement that will create pairwise record comparions
    according to the blocking rule(s).

    Where there are multiple blocking rules, the SQL statement contains logic
    so that duplicate comparisons are not generated.
    """

    settings_obj = linker._settings_obj

    columns_to_select = settings_obj._columns_to_select_for_blocking
    sql_select_expr = ", ".join(columns_to_select)

    link_type = settings_obj._link_type

    if linker._two_dataset_link_only:
        link_type = "two_dataset_link_only"

    if linker._self_link_mode:
        link_type = "self_link"

    where_condition = _sql_gen_where_condition(
        link_type, settings_obj._unique_id_input_columns
    )

    # We could have had a single 'blocking rule'
    # property on the settings object, and avoided this logic but I wanted to be very
    # explicit about the difference between blocking for training
    # and blocking for predictions
    if settings_obj._blocking_rule_for_training:
        blocking_rules = settings_obj._blocking_rule_for_training
    else:
        blocking_rules = settings_obj._blocking_rules_to_generate_predictions

    # Cover the case where there are no blocking rules
    # This is a bit of a hack where if you do a self-join on 'true'
    # you create a cartesian product, rather than having separate code
    # that generates a cross join for the case of no blocking rules
    if not blocking_rules:
        blocking_rules = settings_obj._generate_blocking_rules(["1=1"])

    sqls = []
    for rule in blocking_rules.values():

        not_previous_rules_statement = _sql_gen_and_not_previous_rules(rule)
        matchkey_number = rule.match_key

        # Apply our salted rules (or if no salt is applied, the standard rule)
        for bl_rule in rule.salt:
            sql = f"""
            select
            {sql_select_expr}
            , '{matchkey_number}' as match_key
            from {linker._input_tablename_l} as l
            inner join {linker._input_tablename_r} as r
            on
            {bl_rule}
            {not_previous_rules_statement}
            {where_condition}
            """

            sqls.append(sql)

    sql = "union all".join(sqls)

    if not settings_obj._needs_matchkey_column:
        sql = sql.replace(", '0' as match_key", "")

    return sql
