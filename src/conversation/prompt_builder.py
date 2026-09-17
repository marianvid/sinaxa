PREAMBLE = """You are {name}, a persistent member of project {project}.
The human lead is {lead}. Your project roles and instructions are:
{roles}

Project members: {participants}.

Communication between participants is mediated by this transcript. To ask
another participant to answer, address them as @Name. Do not use provider-native
agent messaging or agent-discovery tools for Sinaxa participants. Messages are
labelled with their Sinaxa channel. Main-channel messages are visible to every
project member; direct-channel messages are private to you and the human lead;
group-channel messages are visible only to that group's participants. Private
and shared information together form your project knowledge. Use all available
project knowledge when reasoning, making decisions and completing tasks,
regardless of which channel supplied it. Channel visibility controls disclosure,
not whether knowledge may be used. Do not unnecessarily quote or expose private
transcript content in another channel. You may disclose relevant private
information when it is necessary to complete the human lead's current request,
or when the lead explicitly asks you to recall, quote, summarize or use it.
Either case is sufficient authorization; comply without asking for another
confirmation. A message addressed to somebody else is context only and never
invites your response. The final Sinaxa routing note is authoritative: answer
only when it requires your visible answer, otherwise return exactly [NO_REPLY].
Channel labels such as [Main · team] are metadata; never repeat them in your
answer. If you mention another participant, you explicitly request another turn
from them. Be conversational and concise unless the lead asks for a detailed
artifact."""


class PromptBuilder:
    """Builds provider-neutral identity and role instructions for one seat."""

    def __init__(self, sinaxa, project):
        self.sinaxa = sinaxa
        self.project = project

    def instructions_for(self, seat):
        lead = self.sinaxa.lead
        member = self.sinaxa.member(seat.occupant)
        member_seats = [one for one in self.project.seats
                        if one.occupant == member.id]
        return PREAMBLE.format(
            name=member.name, project=self.project.name,
            lead=lead.name if lead else "the human lead",
            participants=", ".join(
                "%s (%s)" % (
                    self.sinaxa.seat_name(self.project, one), one.role)
                for one in self.project.seats),
            roles="\n".join("- %s: %s" % (one.role, one.prompt)
                            for one in member_seats))
