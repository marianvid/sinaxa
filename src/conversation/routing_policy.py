class RoutingPolicy:
    """Selects visible responders without knowing engine execution details."""

    def __init__(self, sinaxa, project, session):
        self.sinaxa = sinaxa
        self.project = project
        self.session = session

    def participants(self):
        return [self.project.seat(seat_id)
                for seat_id in self.session.participants]

    def runnable_participants(self):
        return [seat for seat in self.participants()
                if self.sinaxa.seat_runs_engine(seat)]

    def speakers_for(self, text, author_seat=None):
        seats = [seat for seat in self.runnable_participants()
                 if seat.id != author_seat]
        mentioned = self.sinaxa.mentioned(self.project, text, seats)
        if author_seat is None:
            return mentioned or seats
        return mentioned

    def note(self, required):
        if required:
            return ("[Sinaxa routing] Reply in channel %s. This turn requires "
                    "your visible answer." % self.session.name)
        return ("[Sinaxa routing] Update your awareness, but do not produce a "
                "visible reply; return exactly [NO_REPLY].")
