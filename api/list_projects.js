const { state } = require('./_store');

module.exports = (req, res) => {
  res.status(200).json(Object.keys(state.projects));
};
