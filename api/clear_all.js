const { state } = require('./_store');

module.exports = (req, res) => {
  state.chats = {};
  state.current_chat = null;
  state.projects = {};
  state.filesByChat = {};
  state.foldersByChat = {};
  res.status(200).json({ success: true });
};
