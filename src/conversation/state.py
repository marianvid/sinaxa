class Conversation:
    """Mutable delivery state for one seat in one Sinaxa session."""

    def __init__(self, seat_id):
        self.seat_id = seat_id
        self.agent = None
        self.delivered = 0
        self.trouble = None
