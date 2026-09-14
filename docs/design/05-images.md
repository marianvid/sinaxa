# Attachments

Pasted images are content-addressed and stored inside the session `files/`
folder. Transcript messages contain only generated filenames. File-serving
validates the filename before resolving it, and uploads are capped at 24 MB.

Adapters receive absolute local paths. Codex uses local-image turn inputs,
Claude embeds images through its stream protocol, and OpenCode converts the
file to a data URI. When a provider cannot carry an image, the text context
states explicitly that an attachment was not available.
