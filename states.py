from aiogram.fsm.state import StatesGroup, State


class OrderFSM(StatesGroup):
    waiting_details = State()
    waiting_custom_price = State()
    waiting_payment = State()


class PubgFSM(StatesGroup):
    waiting_pubg_id = State()
    waiting_payment = State()


class TopUpFSM(StatesGroup):
    waiting_amount = State()
    waiting_receipt = State()


class SupportFSM(StatesGroup):
    waiting_message = State()


class PromoFSM(StatesGroup):
    waiting_code = State()


class AdminBroadcastFSM(StatesGroup):
    waiting_text = State()


class AdminTicketFSM(StatesGroup):
    waiting_reply = State()


class AdminPromoFSM(StatesGroup):
    waiting_code = State()
    waiting_amount = State()
    waiting_limit = State()

class CalculatorFSM(StatesGroup):
    waiting_amount = State()
