class FactoryError(Exception):
    """A bounded, reportable workflow failure."""


class ConfigError(FactoryError):
    pass


class ContractError(FactoryError):
    pass


class BudgetError(FactoryError):
    pass
