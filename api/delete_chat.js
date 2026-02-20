const { state } = require('./_store');

module.exports = (req, res) => {
  const id = req.query.id;
  if (id && state.chats[id]) {
    const title = state.chats[id].title;
    delete state.chats[id];
    delete state.filesByChat[id];
    delete state.foldersByChat[id];
    if (title && state.projects[title] === id) delete state.projects[title];
    if (state.current_chat === id) state.current_chat = null;
  }
  res.status(200).json({ success: true });
};
