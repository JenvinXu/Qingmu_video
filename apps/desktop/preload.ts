import { contextBridge, ipcRenderer } from 'electron';
contextBridge.exposeInMainWorld('studioDesktop', {
  connection: () => ipcRenderer.invoke('studio:connection'),
  openData: () => ipcRenderer.invoke('studio:open-data'),
  external: (url: string) => ipcRenderer.invoke('studio:external', url),
  saveVideo: (relative: string, name: string) => ipcRenderer.invoke('studio:save-video', relative, name),
  onAccept: (callback: () => void) => {
    const listener = () => callback();
    ipcRenderer.on('studio:accept', listener);
    return () => ipcRenderer.removeListener('studio:accept', listener);
  },
});
