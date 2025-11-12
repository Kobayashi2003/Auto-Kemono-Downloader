## BUG

- RPC模式下有BUG。测试表现为list和tasks命令正常，但是其它大部分命令不能正常工作。
- 需要在缓存posts之前添加对posts响应数据的去重，不知道什么原因，官方的api返回的数据存在有重复的id。

## 待商榷

- 当前的artist.json中的last_date字段的更新时机是在一个download_artist任务完成后更新。我在考虑是否要将其放在每个download_post任务完成后更新，以防止在一个artist有大量未下载作品时，任务中途被打断后重新开始下载时重复抓取过多的已下载作品。但这样会增加文件写入的频率，同时会引入同步问题。

- 当前的重复下载检测实现在了api.py中的download_file中，它会首先通过流式下载获取content-length头，然后检查该文件是否已存在。如果存在则跳过下载。这种方法虽然有效，但会增加一次HTTP请求。我在考虑是否可以增加一个content-length缓存机制，在第一次下载时将content-length存储起来，后续下载时直接在downloader中使用缓存来判断文件是否已存在，从而避免额外的HTTP请求。