"""Sample SMS used by the tests.

These are ILLUSTRATIVE messages written in the general style of Zambian
mobile-money notifications. They are not copied from real operators.
Replace / extend them with real SMS collected during merchant interviews
(remove customers' names and numbers first).
Each sample: (sms_text, expected_provider, expected_direction, expected_amount, expected_ref)
"""

SAMPLES = [
    ("You have received ZMW 250.00 from JOHN BANDA 0961234567 on 2026-10-28 09:14:03. "
     "Transaction ID: 4419328871. Your new balance is ZMW 1,320.50. MTN MoMo",
     "MTN", "in", 250.00, "4419328871"),
    ("MoMo: Payment received K1,200.00 from MARY PHIRI (260971112233) 28/10/2026 10:02. "
     "Ref: MP261028.1002.A55. Bal K2,520.50",
     "MTN", "in", 1200.00, "MP261028.1002.A55"),
    ("Airtel Money: You have received ZMW 85.50 from CHANDA MWALE, 0977654321. "
     "Txn ID: CI261028.1130.B77231. Balance ZMW 605.50. 28-10-2026 11:30",
     "AIRTEL", "in", 85.50, "CI261028.1130.B77231"),
    ("Money received K40 from Esther Zulu 0955443322 via Airtel Money. Trans ID PP2610281301. "
     "New balance K645.50",
     "AIRTEL", "in", 40.00, "PP2610281301"),
    ("Zamtel Money: You have received K500.00 from PETER TEMBO 0951239876. "
     "Transaction ID: ZM88123001. 2026-10-28 14:45:10. Balance: K3,020.50",
     "ZAMTEL", "in", 500.00, "ZM88123001"),
    ("You have sent ZMW 300.00 to WHOLESALE DEPOT 0962223344. Transaction ID: 4419400012. "
     "Fee ZMW 2.50. MTN MoMo",
     "MTN", "out", 300.00, "4419400012"),
]

NOT_PAYMENTS = [
    "Hello, how are you?",
    "Get 2GB data for K10! Dial *117# now. MTN",
    "Your Airtel Money PIN was changed successfully.",
]
