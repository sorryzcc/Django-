import json
import uuid
import logging
import requests
import datetime
import time

from channels.http import AsgiRequest
from django.core.cache import cache
from django_redis import get_redis_connection
from django.http import HttpResponse
from django.http import JsonResponse
from django.views import View
from django.shortcuts import redirect, render
from django.forms import model_to_dict

from autosystem import settings
from main import models
from utils.base import base_utils
from utils.ResponseCode import error_map, RET
from utils.base.api_utils import send_text_by_ai_helper
from utils.base.pushBot_util import bot_push, BotMsgType
from .models import LockQueueInfoModel, LockRefreshLog, SVNPermissionApply, SvnFilePermissionApply
from dashboard.models import ServerManagePermission, SvnGitRelationInfo, GameServerByRainBow, GameServer, TaskRecord, \
    ServerInfo, ClusterSetting

logger = logging.getLogger(__package__)
_cache = get_redis_connection("default")

wechat_url = "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=eed528be-4c1e-4131-bd6f-b0ecfacd77b3"
wechat_url2 = "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=f0970aa5-2873-4ced-88d9-d477551c9acc"

global_ = {
    "trunk": ["主线",
              "IDC主线开发服、主线配置服、DS专属测试服、历程测试服、主线开发服、、主线日构建服、主线开发服(云上)、DS专属测试服(云上)、项目组体验服(云上83)、项目组体验服(云上83)、web_dev等"],
    "Predistribution": ["预发布线",
                        "预发布测试服、预发布日构建服、苹果审核服、外网镜像服、专项测试服、玩家团服、专项测试服(云上75)、预发布日构建服(云上78)、预发布测试服(云上79)、外网镜像服(云上80)、苹果审核服(云上81)、玩家团服(云上82)"],
    "banshen": ["版审线", "版署审核服"],
    "temp": ["temp线", "CE体验服、主线测试服、CE体验服(云上76)、主线测试服(云上73)"],
    "dev": ["跨版本线", "跨版本日构建、跨版本日构建服(云上77)"],
    "dev2": ["dev2线", "数值PVP日构建服(云上193)"],
    "dev3": ["dev3线", "版本兼容开发服(云上66)"],
    "dev4": ["dev4线", "秘宝行动日构建服(云上)"],
    "dev5": ["dev5线", "公会系统服(192)"],
    "Ailab": ["Ailab线", "AILab开发测试服(云上)"],
    "global": ["通用", "克隆服、服务器私服等"]
}
group_list = global_


class ConfigRefreshLock(View):
    @staticmethod
    def post(request):
        info = request.POST.get("info")
        try:
            _info = json.loads(info)
        except ValueError as e:
            logger.exception("info: {}, exception: {}".format(info, e))

            return JsonResponse({
                "code": -1,
                "msg": "锁操作请求错误！参数有误"
            })

        # 读取参数信息
        svr = _info["svr"]
        user = _info["user"]
        cmd = _info["cmd"]

        lock_info = cache.get("lock_{}".format(svr))

        # 查询锁状态
        if cmd == "status":
            if lock_info:
                return JsonResponse({
                    "code": 0,
                    "current_user": lock_info,
                    "current_status": "lock",
                    "msg": "获取锁状态成功"
                })
            else:
                return JsonResponse({
                    "code": 0,
                    "current_user": user,
                    "current_status": "unlock",
                    "msg": "获取锁状态成功"
                })

        # 解锁
        elif cmd == "unlock":
            if lock_info:
                if lock_info == user:
                    # 若锁用户与解锁用户相同，则解锁
                    cache.delete("lock_{}".format(svr))
                    # 发送解锁提醒
                    g_data = group_list.get(svr, ['unknown', 'unknown Server'])
                    context = "# 锁表锁状态提醒\n ## <@{}> 已完成刷表并解锁\n ## 以下服务器已开放刷表：\n{}".format(
                        user,
                        g_data[1]
                    )
                    _data = json.dumps({
                        "msgtype": "markdown",
                        "markdown": {
                            "content": context
                        }
                    })
                    headers = {'Content-Type': 'application/json'}
                    # requests.post(wechat_url, headers=headers, data=_data)
                    requests.post(wechat_url2, headers=headers, data=_data)

                    return JsonResponse({
                        "code": 0,
                        "current_user": user,
                        "current_status": "unlock",
                        "msg": "已解锁"
                    })
                else:
                    return JsonResponse({
                        "code": -1,
                        "current_user": lock_info,
                        "current_status": "lock",
                        "msg": "{}正在使用，请稍后！".format(lock_info)
                    })
            else:
                # 若无人加锁，直接提示解锁成功
                return JsonResponse({
                    "code": 0,
                    "current_user": user,
                    "current_status": "unlock",
                    "msg": "已解锁"
                })

        # 上锁
        elif cmd == "lock":
            if lock_info:
                # 已上锁，则禁止上锁
                return JsonResponse({
                    "code": -1,
                    "current_user": lock_info,
                    "current_status": "lock",
                    "msg": "{}正在使用，请稍后！".format(lock_info)
                })
            else:
                # 上锁！
                cache.set("lock_{}".format(svr), user, 60 * 60 * 24)
                # 发送上锁提醒
                g_data = group_list.get(svr, ['unknown', 'unknown Server'])
                context = "# 锁表锁状态提醒\n ## <@{}> 正在 {} 上进行刷表操作\n ## 以下服务器已被上锁：\n{}".format(
                    user,
                    g_data[0],
                    g_data[1]
                )
                _data = json.dumps({
                    "msgtype": "markdown",
                    "markdown": {
                        "content": context
                    }
                })
                headers = {'Content-Type': 'application/json'}
                # requests.post(wechat_url, headers=headers, data=_data)
                requests.post(wechat_url2, headers=headers, data=_data)

                return JsonResponse({
                    "code": 0,
                    "current_user": user,
                    "current_status": "lock",
                    "msg": "已上锁"
                })

        else:
            return JsonResponse({
                "code": -1,
                "msg": "锁操作请求错误！参数有误"
            })

class ConfigRefreshForceUnlock(View):
    @staticmethod
    def post(request):
        info = request.POST.get("info")
        try:
            _info = json.loads(info)
            logger.info(info)
        except ValueError as e:
            logger.exception("info: {}, exception: {}".format(info, e))

            return JsonResponse({
                "code": -1,
                "msg": "锁操作请求错误！参数有误"
            })

        # 读取参数信息
        svr = _info["svr"]
        user = _info["user"]
        cmd = _info["cmd"]

        lock_info = cache.get("lock_{}".format(svr))

        if lock_info and cmd == "unlock":
            cache.delete("lock_{}".format(svr))
            # 发送强制解锁提醒
            g_data = group_list.get(svr, ['unknown', 'unknown Server'])
            context = "# 锁表锁状态提醒\n ## 震惊！<@{}>强制解锁了 {} 的刷表锁\n ## 以下服务器已开放刷表：\n{}".format(
                user,
                g_data[0],
                g_data[1]
            )
            _data = json.dumps({
                "msgtype": "markdown",
                "markdown": {
                    "content": context
                }
            })
            headers = {'Content-Type': 'application/json'}
            requests.post(wechat_url, headers=headers, data=_data)
            requests.post(wechat_url2, headers=headers, data=_data)

            return JsonResponse({
                "code": 0,
                "current_user": user,
                "current_status": "unlock",
                "msg": "强制解锁成功，清谨慎使用强制解锁！"
            })

        else:
            if cmd == "unlock":
                return JsonResponse({
                    "code": -1,
                    "current_user": user,
                    "current_status": "unlock",
                    "msg": "未上锁，如果状态错误，请联系v_bwwbchen"
                })
            else:
                return JsonResponse({
                    "code": -1,
                    "current_user": user,
                    "current_status": "unlock",
                    "msg": "错误命令，该接口只能用于强制解锁"
                })

class SvnLockStatusView(View):
    def get(self, request, group, rtx):
        try:
            rtx = rtx.split("-")[0]
            group_data = SvnGitRelationInfo.objects.get(branch_refresh_group=group)
            if group_data.lock_status == 1:
                commit_list_key = "{}_svn_unlock".format(group_data.branch_name)
                for _v in _cache.lrange(commit_list_key, 0, -1):
                    if _v.decode() == rtx:
                        _cache.lrem(commit_list_key, 0, rtx)
                        return JsonResponse({
                            "code": RET.OK,
                            "msg": "SVN已经开闸",
                            "data": "SVN已经开闸"
                        })

                return JsonResponse({
                    "code": 4100,
                    "msg": "svn已上锁",
                    "data": "svn已上锁"
                })
            else:
                return JsonResponse({
                    "code": RET.OK,
                    "msg": error_map[RET.OK],
                    "data": "SVN未上锁"
                })

        except Exception as e:
            return JsonResponse({
                "code": RET.NODATA,
                "msg": error_map[RET.NODATA],
                "data": "SVN信息异常" + str(e)
            })


class SvnLockView(View):
    @staticmethod
    def get(request, branch, op, rtx):
        try:
            group_data = SvnGitRelationInfo.objects.get(branch_lock_name=branch)
            if op == "lock":
                if rtx == "all":
                    group_data.lock_status = 1
                    group_data.save()
            elif op == "unlock":
                if rtx == "all":
                    group_data.lock_status = 0
                    group_data.save()
                else:
                    commit_list_key = "{}_svn_unlock".format(group_data.branch_name)
                    _cache.lpush(commit_list_key, rtx)
            else:
                raise Exception("UNKNOW OP")
            return JsonResponse({
                "code": RET.OK,
                "msg": error_map[RET.OK],
                "data": []
            })
        except Exception as e:
            return JsonResponse({
                "code": RET.NODATA,
                "msg": error_map[RET.NODATA],
                "data": str(e)
            })


class ServerLockView(View):
    @staticmethod
    def get(request: "AsgiRequest"):
        world_id = request.GET.get("world_id", None)
        user = request.GET.get("user", None)
        tool_branch = request.GET.get("tool_branch", None)

        server_lock = False
        branch_lock = False

        if not world_id:
            return JsonResponse({
                "code": RET.OK,
                "msg": error_map[RET.OK],
                "data": {
                    "server_lock": True,
                    "branch_lock": True
                }
            })

        server_info = ServerInfo.objects.filter(world_id=world_id, in_use=1).first()

        if not server_info:
            if world_id:
                send_text_by_ai_helper([], ["v_bwwbchen", "vulpeswu"], f"服务器环境ID{world_id}缺少锁配置，请及时配置。")
            return JsonResponse({
                "code": RET.NODATA,
                "msg": error_map[RET.NODATA],
                "data": {
                    "server_lock": server_lock,
                    "branch_lock": branch_lock
                }
            })

        if server_info.branch != tool_branch:
            branch_lock = True

        server_lock = server_info.lock_status

        # 添加用户刷表权限白名单判断
        if world_id and user and ServerInfo.hasRefreshTablePermission(int(world_id), user):
            server_lock = False
            branch_lock = False

        whitelist = cache.get(f"server_lock_{world_id}_white_list", [])
        if user in whitelist:
            server_lock = False
            branch_lock = False

        return JsonResponse({
            "code": RET.OK,
            "msg": error_map[RET.OK],
            "data": {
                "server_lock": server_lock,
                "branch_lock": branch_lock
            }
        })

    @staticmethod
    def post(request: "AsgiRequest"):
        _data = json.loads(request.body.decode())

        world_id = _data.get("world_id")
        lock_status = _data.get("lock_status")

        if not all([world_id]):
            return JsonResponse({
                "code": RET.PARAM_ERR,
                "msg": error_map[RET.PARAM_ERR],
                "data": []
            })

        task_record = TaskRecord.create_log(
            operator=request.user,
            task_type=TaskRecord.TaskTypeEnum.ServerLock,
            post_json=json.dumps(_data),
            description=f'服务器刷表锁\n 服务器id:【{world_id}】 锁状态:【{lock_status}】'
        )

        game_server_rainbow = GameServerByRainBow()
        status, _data = game_server_rainbow.get_server_list(in_use=1, world_id=world_id)
        if not status:
            task_record.save_fail(resp=f'查询七彩石错误 {_data}')
            return JsonResponse({
                "code": RET.SERVER_ERR,
                "msg": _data
            })

        ServerInfo.objects.filter(world_id=world_id, in_use=1).update(lock_status=lock_status)

        if len(_data) == 0:
            if world_id:
                send_text_by_ai_helper([], ["v_bwwbchen", "vulpeswu"], f"服务器环境ID{world_id}缺少锁配置，请及时配置。")
            task_record.save_fail(resp=f'查询七彩石为空')
            return JsonResponse({
                "code": RET.NODATA,
                "msg": error_map[RET.NODATA],
                "data": {}
            })
        _data = _data[0]
        _data['lock_status'] = lock_status
        status, _msg = game_server_rainbow.update_server_list(**_data)
        if not status:
            task_record.save_fail(resp=f'更新七彩石错误 {_msg}')
            return JsonResponse({
                "code": RET.SERVER_ERR,
                "msg": _msg
            })
        status, _msg = game_server_rainbow.release_task('admin')
        if not status:
            task_record.save_fail(resp=f'发布七彩石错误 {_msg}')
            return JsonResponse({
                "code": RET.SERVER_ERR,
                "msg": _msg
            })

        task_record.save_success(_data)
        return JsonResponse({
            "code": RET.OK,
            "msg": error_map[RET.OK],
            "data": [_data]
        })


class ServerLockWhitelistView(View):
    @staticmethod
    def get(request: "AsgiRequest"):
        world_id = request.GET.get("world_id", None)

        # 这一段暂代put的功能
        user = request.GET.get("user", None)
        is_add = request.GET.get("is_add", None)

        # 权限信息检查
        if not request.user.is_authenticated:
            redirect_uri = "http://{}/v2/api/login/".format(settings.CONF["BASE_CONF"]["WEB_SERVER_IP"])

            return redirect('https://passport.woa.com/modules/passport/signin.ashx?url={}?url={}'.format(
                redirect_uri, request.build_absolute_uri(request.get_full_path())))

        # server, created = GameServer.objects.get_or_create(world_id=world_id, in_use=1)
        gameServerRainBow = GameServerByRainBow()
        status, _data = gameServerRainBow.get_server_list(world_id=world_id, in_use=1)
        if not status:
            return JsonResponse({
                "code": RET.SERVER_ERR,
                "msg": _data
            })
        if len(_data) == 0:
            if world_id:
                send_text_by_ai_helper([], ["v_bwwbchen", "vulpeswu"], f"服务器环境ID{world_id}缺少锁配置，请及时配置。")
            return render(request, "server_lock_tips.html", {
                "code": RET.NODATA,
                "msg": error_map[RET.NODATA],
                "data": {}
            })
        _data = _data[0]

        hasPermission = ServerManagePermission.hasPermission(request.user.account, [])
        if user and is_add and (not hasPermission):
            # and request.user.account not in [
            #     "reyingpeng", "mathewliu", "v_bwwbchen", "v_jingheke", "asdwang", "vulpeswu", "smeagleqiao",
            #     "zijuezhang", "welkinwang", "zhengxuli", "arthuryu", "binnywang", "feynhan", "suxanlin", "athenaliu",
            #     "markling",
            # ]:
            return render(request, "server_lock_tips.html", {
                "code": "-1",
                "msg": "失败",
                "data": "权限错误：缺少处理申请的权限！"
            })

        if is_add == "true":
            if world_id and user and ServerInfo.hasRefreshTablePermission(int(world_id), user):
                ServerInfo.addWhitelist(int(world_id), user)
                # application_form = cache.get("server_lock_whitelist_application_form", [])
                # if user in application_form:
                #     application_form.remove(user)
                #     cache.set("server_lock_whitelist_application_form", application_form)

                whitelist = cache.get(f"server_lock_{world_id}_white_list", [])
                whitelist.append(user)
                cache.set(f"server_lock_{world_id}_white_list", whitelist, 60 * 60 * 24)

                send_text_by_ai_helper([], [user], f"你的申请 {_data['name']}刷表 已通过")
                send_text_by_ai_helper(["ww3033145965"], [], f"{user}的申请 {_data['name']}刷表 已通过")
            else:
                return render(request, "server_lock_tips.html", {
                    "code": "-1",
                    "msg": "失败",
                    "data": "申请已被处理或失效"
                })
        elif is_add == "false":
            #   永久白名单改为数据库存储
            if world_id and user and ServerInfo.hasRefreshTablePermission(int(world_id), user):
                # application_form = cache.get("server_lock_whitelist_application_form", [])
                # if user in application_form:
                # application_form.remove(user)
                # cache.set("server_lock_whitelist_application_form", application_form)
                ServerInfo.delWhitelist(int(world_id), user)
                send_text_by_ai_helper([], [user], "你的申请 {}刷表 已拒绝".format(_data['name']))
                send_text_by_ai_helper(["ww3033145965"], [], f"{user}的申请 {_data['name']}刷表 已拒绝")

        whitelist = cache.get("server_lock_{}_white_list".format(world_id), [])

        return render(request, "server_lock_tips.html", {
            "code": RET.OK,
            "msg": error_map[RET.OK],
            "data": whitelist
        })

    @staticmethod
    def post(request: "AsgiRequest"):
        _data = json.loads(request.body.decode())

        world_id = _data.get("world_id")
        user = _data.get("user")
        desc = _data.get("desc", "")

        if not all([world_id, user]):
            return JsonResponse({
                "code": RET.PARAM_ERR,
                "msg": error_map[RET.PARAM_ERR],
                "data": []
            })

        # server, created = GameServer.objects.get_or_create(world_id=world_id, in_use=1)
        gameServerRainBow = GameServerByRainBow()
        status, _data = gameServerRainBow.get_server_list(world_id=world_id, in_use=1)
        if not status:
            return JsonResponse({
                "code": RET.SERVER_ERR,
                "msg": _data
            })
        if len(_data) == 0:
            if world_id:
                send_text_by_ai_helper([], ["v_bwwbchen", "vulpeswu"], f"服务器环境ID{world_id}缺少锁配置，请及时配置。")
            return JsonResponse({
                "code": RET.NODATA,
                "msg": error_map[RET.NODATA],
                "data": {}
            })
        _data = _data[0]

        # send_text_by_ai_helper(["ww3000301478"], ["v_bwwbchen", "vulpeswu"], "服务器环境ID{}缺少锁配置，请及时配置。".format(world_id))
        #   添加权限申请
        apply_obj = SVNPermissionApply.addApply(user, world_id, _data['branch'])

        r = requests.post(
            "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=e6ba466b-d8b6-44a2-bd9e-7f3f5ea0b687",
            # "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=e7ba94c5-090f-4ada-abf6-f5830d93f7e3",
            json={
                "msgtype": "template_card",
                "template_card": {
                    "card_type": "text_notice",
                    "source": {
                        "desc": "合金工具平台"
                    },
                    "main_title": {
                        "title": f"【{_data['name']}】刷表申请",
                        "desc": f"@{user}正在发起刷表申请\n{desc}"
                    },
                    "horizontal_content_list": [
                        {
                            "keyname": "点击详情查看",
                            "value": "详情",
                            "type": 1,
                            # "url": f"http://{settings.CONF['BASE_CONF']['WEB_SERVER_IP']}/api/server_lock_whitelist/?world_id={world_id}&user={user}&is_add=true"
                            "url": f"https://{settings.CONF['BASE_CONF']['WEB_SERVER_IP']}/page/svnPermissionDetail?apply_user={apply_obj.apply_user}&world_id={apply_obj.world_id}"
                        },
                        # {
                        #     "keyname": "点击",
                        #     "value": "拒绝",
                        #     "type": 1,
                        #     "url": f"http://{settings.CONF['BASE_CONF']['WEB_SERVER_IP']}/api/server_lock_whitelist/?world_id={world_id}&user={user}&is_add=false"
                        # },
                    ],
                    "card_action": {
                        "type": 1,
                        "url": f"https://{settings.CONF['BASE_CONF']['WEB_SERVER_IP']}/",
                        "appid": "APPID",
                        "pagepath": "PAGEPATH"
                    }
                }
            }
        )

        if r.status_code == 200:
            result = r.json()
            if result["errcode"] != 0:
                return JsonResponse({
                    "code": result["errcode"],
                    "msg": result["errmsg"],
                    "data": "发送企业微信消息失败！错误信息: {}".format(base_utils.bytes2str(result["errmsg"]))
                })
        else:
            return JsonResponse({
                "code": RET.SERVER_ERR,
                "msg": error_map[RET.SERVER_ERR],
                "data": ["发送企业微信消息失败！错误信息:", base_utils.bytes2str(r.content)]
            })

        #   不再使用缓存记录刷表申请
        # application_form = cache.get("server_lock_whitelist_application_form", [])
        # application_form.append(user)
        # cache.set("server_lock_whitelist_application_form", application_form, 60 * 60 * 24)

        return JsonResponse({
            "code": RET.OK,
            "msg": error_map[RET.OK],
            "data": []
        })

    @staticmethod
    def put(request: "AsgiRequest"):
        _data = json.loads(request.body.decode())

        world_id = _data.get("world_id")
        user = _data.get("user")

        if not all([world_id, user]):
            return JsonResponse({
                "code": RET.PARAM_ERR,
                "msg": error_map[RET.PARAM_ERR],
                "data": []
            })

        whitelist = cache.get(f"server_lock_{world_id}_white_list", [])
        whitelist.append(user)
        cache.set(f"server_lock_{world_id}_white_list", whitelist, 60 * 60 * 24)

        return JsonResponse({
            "code": RET.OK,
            "msg": error_map[RET.OK],
            "data": whitelist
        })

    @staticmethod
    def delete(request: "AsgiRequest"):
        _data = json.loads(request.body.decode())

        world_id = _data.get("world_id")
        user = _data.get("user")

        if not all([world_id, user]):
            return JsonResponse({
                "code": RET.PARAM_ERR,
                "msg": error_map[RET.PARAM_ERR],
                "data": []
            })

        whitelist = cache.get(f"server_lock_{world_id}_white_list", [])
        if user in whitelist:
            whitelist.remove(user)
            cache.set(f"server_lock_{world_id}_white_list", whitelist, 60 * 60 * 24)
        else:
            return JsonResponse({
                "code": RET.DATA_ERR,
                "msg": error_map[RET.DATA_ERR],
                "data": whitelist
            })

        return JsonResponse({
            "code": RET.OK,
            "msg": error_map[RET.OK],
            "data": whitelist
        })


class SVNPermissionList(View):

    @staticmethod
    def get(request: AsgiRequest):
        '''获取SVN权限申请列表'''

        apply_user = request.GET.get('apply_user', '')
        review_user_query = request.GET.get('review_user', '')
        # 权限信息检查
        if not request.user.is_authenticated:
            redirect_uri = "http://{}/v2/api/login/".format(settings.CONF["BASE_CONF"]["WEB_SERVER_IP"])

            return redirect('https://passport.woa.com/modules/passport/signin.ashx?url={}?url={}'.format(
                redirect_uri, request.build_absolute_uri(request.get_full_path())))

        review_user = request.user.account
        hasPermission = ServerManagePermission.hasPermission(review_user, [])
        if not hasPermission:
            return JsonResponse({
                "code": "-1",
                "msg": "失败",
                "data": "权限错误：缺少处理申请的权限！"
            })
        filterObj = {}
        if apply_user:
            filterObj['apply_user'] = apply_user
        if review_user_query:
            filterObj['reivew_user'] = review_user_query
        querySets = SVNPermissionApply.objects.filter(**filterObj).order_by('review_status','-create_time').values()
        datas = [dict(item) for item in querySets]

        return JsonResponse({
            'code': RET.OK,
            'msg': error_map[RET.OK],
            'data': datas
        })


class SVNPermissionApplyDetail(View):

    @staticmethod
    def get(request: AsgiRequest):
        '''获取SVN权限申请详情'''

        apply_user = request.GET.get('apply_user', '')
        review_user_query = request.GET.get('review_user', '')
        world_id = request.GET.get('world_id')
        id = request.GET.get('id')
        # 权限信息检查

        review_user = request.user.account
        hasPermission = ServerManagePermission.hasPermission(review_user, [])
        if not hasPermission:
            return JsonResponse({
                "code": "-1",
                "msg": "失败",
                "data": "权限错误：缺少处理申请的权限！"
            })

        obj = SVNPermissionApply.objects.filter(world_id=world_id, apply_user=apply_user).order_by('-create_time').first()
        if not obj:
            return JsonResponse({
                'code': RET.NODATA,
                'msg': error_map[RET.NODATA],
                'data': False,
            })

        gameServerRainBow = GameServerByRainBow()
        status, _data = gameServerRainBow.get_server_list(world_id=obj.world_id, in_use=1)
        if not status or len(_data) <= 0:
            return JsonResponse({
                "code": RET.SERVER_ERR,
                "msg": _data,
                'data': ''
            })
        data = model_to_dict(obj)

        data.update(_data[0])
        return JsonResponse({
            'code': RET.OK,
            'msg': error_map[RET.OK],
            'data': data
        })


class SVNPermissionReview(View):
    '''审核SVN权限'''

    @staticmethod
    def post(request):
        _data = json.loads(request.body.decode())

        # 权限信息检查
        if not request.user.is_authenticated:
            redirect_uri = "http://{}/v2/api/login/".format(settings.CONF["BASE_CONF"]["WEB_SERVER_IP"])

            return redirect('https://passport.woa.com/modules/passport/signin.ashx?url={}?url={}'.format(
                redirect_uri, request.build_absolute_uri(request.get_full_path())))

        review_user = request.user.account
        hasPermission = ServerManagePermission.hasPermission(review_user, [])
        if not hasPermission:
            return JsonResponse({
                "code": "-1",
                "msg": "失败",
                "data": "权限错误：缺少处理申请的权限！"
            })

        apply_user = _data.get('apply_user')
        svn_upload = _data.get('svn_upload', False)
        refresh_table = _data.get('refresh_table', False)
        world_id = _data.get('world_id')

        if not all([apply_user, world_id]):
            return JsonResponse({
                'code': RET.PARAM_ERR,
                'msg': error_map[RET.PARAM_ERR],
                'data': False,
            })

        gameServerRainBow = GameServerByRainBow()
        status, _data = gameServerRainBow.get_server_list(world_id=world_id, in_use=1)
        if not status or len(_data) <= 0:
            return JsonResponse({
                "code": RET.SERVER_ERR,
                "msg": _data,
                'data': '',
            })
        _data = _data[0]

        if all([svn_upload, refresh_table]):
            SVNPermissionApply.passApply(review_user, apply_user, world_id, _data['branch'], svn_upload, refresh_table)
            send_text_by_ai_helper([], [apply_user], f"你的申请 {_data['name']}刷表 已通过")
            send_text_by_ai_helper(["ww3033145965"], [], f"{apply_user}的申请 {_data['name']}刷表 已通过")
        elif svn_upload:
            SVNPermissionApply.passApply(review_user, apply_user, world_id, _data['branch'], svn_upload, refresh_table)
            send_text_by_ai_helper([], [apply_user], f"你的申请 {_data['name']}SVN锁 已通过")
            send_text_by_ai_helper(["ww3033145965"], [], f"{apply_user}的申请 {_data['name']}SVN锁 已通过")
        elif refresh_table:
            SVNPermissionApply.passApply(review_user, apply_user, world_id, _data['branch'], svn_upload, refresh_table)
            send_text_by_ai_helper([], [apply_user], f"你的申请 {_data['name']}刷表 已通过")
            send_text_by_ai_helper(["ww3033145965"], [], f"{apply_user}的申请 {_data['name']}刷表 已通过")
        else:
            SVNPermissionApply.rejectApply(review_user,apply_user,world_id,_data['branch'])
            send_text_by_ai_helper([], [apply_user], "你的申请 {}刷表 已拒绝".format(_data['name']))
            send_text_by_ai_helper(["ww3033145965"], [], f"{apply_user}的申请 {_data['name']}刷表 已拒绝")

        return JsonResponse({
            'code': RET.OK,
            'msg': error_map[RET.OK],
            'data': True
        })


class SVNPermissionApplyView(View):
    '''申请SVN权限'''

    @staticmethod
    def post(request):
        _data = json.loads(request.body.decode())

        # 权限信息检查
        if not request.user.is_authenticated:
            redirect_uri = "http://{}/v2/api/login/".format(settings.CONF["BASE_CONF"]["WEB_SERVER_IP"])

            return redirect('https://passport.woa.com/modules/passport/signin.ashx?url={}?url={}'.format(
                redirect_uri, request.build_absolute_uri(request.get_full_path())))

        apply_user = _data.get('apply_user')
        svn_upload = _data.get('svn_upload', False)
        refresh_table = _data.get('refresh_table', False)
        world_id = _data.get('world_id')
        branch = _data.get('branch')

        if not all([apply_user, world_id, branch]):
            return JsonResponse({
                'code': RET.PARAM_ERR,
                'msg': error_map[RET.PARAM_ERR],
                'data': False,
            })

        SVNPermissionApply.addApply(apply_user, world_id, svn_upload, refresh_table)

        return JsonResponse({
            'code': RET.OK,
            'msg': error_map[RET.OK],
            'data': True
        })


class SVNFilePermissionApplyDetail(View):
    @staticmethod
    def get(request: AsgiRequest):
        """获取SVN文件锁权限申请详情"""
        apply_id = request.GET.get('apply_id')

        try:
            apply = SvnFilePermissionApply.objects.get(apply_id=apply_id)
        except SvnFilePermissionApply.DoesNotExist:
            return JsonResponse({
                'code': RET.NODATA,
                'msg': error_map[RET.NODATA],
                'data': {}
            })

        return JsonResponse({
            'code': RET.OK,
            'msg': error_map[RET.OK],
            'data': model_to_dict(apply)
        })


class SVNFilePermissionReview(View):
    """审核SVN文件锁权限"""

    @staticmethod
    def post(request):
        _data = json.loads(request.body.decode())
        apply_id = _data.get('apply_id')
        file_review_status = _data.get('file_review_status')

        review_user = request.user.account

        logger.debug(SvnFilePermissionApply.ReviewStatus)
        if file_review_status not in SvnFilePermissionApply.ReviewStatus:
            return JsonResponse({
                'code': RET.PARAM_ERR,
                'msg': error_map[RET.PARAM_ERR],
                'data': False,
            })

        try:
            apply = SvnFilePermissionApply.objects.get(apply_id=apply_id)
            branch = SvnGitRelationInfo.objects.get(svn_branch_name=apply.svn_branch)
        except SvnFilePermissionApply.DoesNotExist:
            return JsonResponse({
                'code': RET.NODATA,
                'msg': '申请不存在',
                'data': {}
            })
        except SvnGitRelationInfo.DoesNotExist:
            return JsonResponse({
                'code': RET.NODATA,
                'msg': '分支不存在',
                'data': {}
            })

        if review_user not in apply.file_review_user:
            return JsonResponse({
                'code': RET.ROLE_ERR,
                'msg': '没有审批权限',
                'data': {}
            })

        apply.file_review_status = file_review_status
        apply.save()

        lock_status = branch.svn_lock_status
        whitelist = branch.svn_lock_whitelist.split(',') if branch.svn_lock_whitelist else []
        disposable_whitelist = branch.svn_lock_disposable_whitelist.split(',') if branch.svn_lock_disposable_whitelist else []

        if file_review_status == SvnFilePermissionApply.ReviewStatus.Pass:
            if lock_status:
                if apply.apply_user not in whitelist and apply.apply_user not in disposable_whitelist:
                    # msg = f"你的申请 【{apply_id}】文件提交 已通过，请找@reyingpeng，@markling申请开闸"
                    msg = f"你的申请 【{apply_id}】文件提交 已通过，请找@markling申请开闸"
                else:
                    msg = f"你的申请 【{apply_id}】文件提交  已通过，请尽快提交"
            else:
                msg = f"你的申请 【{apply_id}】文件提交  已通过，请尽快提交"
        else:
            msg = f"你的申请 【{apply_id}】文件提交  已被拒绝，请找{','.join(['@' + user for user in apply.file_review_user.split(',')])}确认"

        send_text_by_ai_helper([], [apply.apply_user], msg)
        send_text_by_ai_helper(['ww189521742269345'], [], msg)

        return JsonResponse({
            'code': RET.OK,
            'msg': error_map[RET.OK],
            'data': True
        })
