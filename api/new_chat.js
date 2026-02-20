const { state, ensureChat, sanitizeName } = require('./_store');

module.exports = (req, res) => {
  const body = req.body || {};
  const clean = sanitizeName(body.project_name);
  if (state.projects[clean]) {
    const cid = state.projects[clean];
    state.current_chat = cid;
    return res.status(200).json({ chat_id: cid, project_name: clean, exists: true });
  }

  const id = crypto.randomUUID();
  state.chats[id] = { title: clean, messages: [] };
  state.projects[clean] = id;
  state.current_chat = id;
  ensureChat(id);
  return res.status(200).json({ chat_id: id, project_name: clean });
};
