const { state } = require('./_store');

module.exports = (req, res) => {
  res.status(200).json({ chats: state.chats, current_chat: state.current_chat });
};
