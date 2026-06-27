import api from './index'

export const filesystemApi = {
  browse(path?: string): Promise<any> {
    return api.get('/filesystem/browse', { params: path ? { path } : undefined })
  },
}
