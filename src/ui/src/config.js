const _raw = window.API_URL
const API_URL = (_raw && _raw !== '__API_URL__') ? _raw : '/api'

const _rawBranch = window.KIO_BRANCH
const KIO_BRANCH = (_rawBranch && _rawBranch !== '__KIO_BRANCH__') ? _rawBranch : ''

const _rawShowFF = window.SHOW_FEATURE_FLAGS
const SHOW_FEATURE_FLAGS =
  (_rawShowFF && _rawShowFF !== '__SHOW_FEATURE_FLAGS__')
    ? _rawShowFF === 'True'
    : import.meta.env.VITE_SHOW_FEATURE_FLAGS === 'True'

export { API_URL, KIO_BRANCH, SHOW_FEATURE_FLAGS }
