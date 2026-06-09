const _raw = window.API_URL
const API_URL = (_raw && _raw !== '__API_URL__') ? _raw : '/api'

const _rawBranch = window.KIO_BRANCH
const KIO_BRANCH = (_rawBranch && _rawBranch !== '__KIO_BRANCH__') ? _rawBranch : ''

export { API_URL, KIO_BRANCH }
