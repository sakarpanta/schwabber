from dataclasses import dataclass


@dataclass(frozen=True)
class ConceptDefinition:
    unit: str
    duration: bool
    aliases: tuple[tuple[str, str], ...]


CONCEPTS = {
    "revenue": ConceptDefinition(
        "USD",
        True,
        (
            ("us-gaap", "RevenueFromContractWithCustomerExcludingAssessedTax"),
            ("us-gaap", "Revenues"),
            ("us-gaap", "SalesRevenueNet"),
            ("ifrs-full", "Revenue"),
        ),
    ),
    "net_income": ConceptDefinition(
        "USD", True, (("us-gaap", "NetIncomeLoss"), ("ifrs-full", "ProfitLoss"))
    ),
    "diluted_eps": ConceptDefinition(
        "USD/shares",
        True,
        (
            ("us-gaap", "EarningsPerShareDiluted"),
            ("us-gaap", "DilutedEarningsLossPerShare"),
            ("ifrs-full", "DilutedEarningsLossPerShare"),
        ),
    ),
    "assets": ConceptDefinition(
        "USD", False, (("us-gaap", "Assets"), ("ifrs-full", "Assets"))
    ),
    "liabilities": ConceptDefinition(
        "USD", False, (("us-gaap", "Liabilities"), ("ifrs-full", "Liabilities"))
    ),
    "operating_cash_flow": ConceptDefinition(
        "USD",
        True,
        (
            ("us-gaap", "NetCashProvidedByUsedInOperatingActivities"),
            ("ifrs-full", "CashFlowsFromUsedInOperatingActivities"),
        ),
    ),
    "capital_expenditure": ConceptDefinition(
        "USD",
        True,
        (
            ("us-gaap", "PaymentsToAcquirePropertyPlantAndEquipment"),
            ("ifrs-full", "PurchaseOfPropertyPlantAndEquipment"),
        ),
    ),
}
