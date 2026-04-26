from aiogram.fsm.state import State, StatesGroup


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
    waiting_ticket_reply = State()


class AdminBroadcastFSM(StatesGroup):
    waiting_text = State()


class AdminTicketFSM(StatesGroup):
    waiting_reply = State()


class AdminOrderFSM(StatesGroup):
    waiting_message = State()


class AdminProductFSM(StatesGroup):
    waiting_price = State()


class NoCommentFSM(StatesGroup):
    waiting_report = State()


class CalculatorFSM(StatesGroup):
    waiting_amount = State()
