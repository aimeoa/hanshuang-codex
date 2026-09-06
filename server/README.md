# 寒霜破甲工具 - 服务端

## 部署步骤

### Linux (Ubuntu/Debian)
\\\ash
chmod +x deploy.sh
./deploy.sh
\\\

### Windows Server
\\\cmd
pip install -r requirements.txt
uvicorn main:app --host 0.0.0.0 --port 8000
\\\

## API 接口

| 接口 | 方法 | 说明 |
|------|------|------|
| /api/login | POST | 用户登录 |
| /api/register | POST | 用户注册 |
| /api/check_update | GET | 检查更新 |
| /api/admin/push_version | POST | 发布新版本（管理员） |
| /api/admin/push_announcement | POST | 发布公告（管理员） |

## 发布新版本
\\\ash
curl -X POST http://localhost:8000/api/admin/push_version -d "version=1.1.0&download_url=http://xxx/exe&changelog=修复了xxx"
\\\

## 数据库
SQLite 文件：hanshuang.db（自动创建）
