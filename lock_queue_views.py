import base64
import datetime
import json
import logging
import re
import traceback

import requests
from channels.http import AsgiRequest
from django.contrib.auth.models import AnonymousUser
from django.core.cache import cache
from django.core.paginator import Paginator, EmptyPage
from django.db.models import Q, F
from django.http import JsonResponse
from django.views import View

from . import svn_hook_message
from .models import RegularBus, SvnLockReg, TCR, SvnFilePermissionApply

from .TencentGitUtil import create_patch_sets_review, create_svn_review
from autosystem import settings
from dashboard.models import SvnGitRelationInfo, TaskRecord, Svn4ClientEngine
from utils import devops
from utils.base import base_utils, tapd_utils
from utils.ResponseCode import error_map, RET
from utils.base.version_utils import Svn

logger = logging.getLogger(__package__)

class SvnLockView(View):
    @staticmethod
    def hook_response(status: 'int', message: 'str'):
        try:
            response = JsonResponse({
                "status": status,
                "message": message
            }, json_dumps_params={"ensure_ascii": False})
        except Exception as e:
            traceback.print_exc()
            response = JsonResponse({
                "status": 500,
                "message": "服务器校验错误，请联系服务器小助手协助检查！"
            }, json_dumps_params={"ensure_ascii": False})

        return response

    @staticmethod
    def get(request):
        branch = request.GET.get("branch", None)
        # 兼容旧版逻辑
        version = request.GET.get("version", None)
        user = request.GET.get("userName", None)
        page = request.GET.get("page", 1)
        page_size = request.GET.get("pageSize", 15)

        if version is not None:
            branch = version

        if branch:
            branch_info = SvnGitRelationInfo.objects.filter(svn_branch_name=branch).values()
            if len(branch_info):
                branch_info = branch_info.first()

                if user is not None:
                    svn_lock_status = branch_info["svn_lock_status"]
                    svn_lock_blacklist = branch_info["svn_lock_blacklist"].split(",") if branch_info["svn_lock_blacklist"] else []
                    svn_lock_whitelist = branch_info["svn_lock_whitelist"].split(",") if branch_info["svn_lock_whitelist"] else []
                    svn_lock_disposable_whitelist = branch_info["svn_lock_disposable_whitelist"].split(",") if branch_info["svn_lock_disposable_whitelist"] else []

                    if user in svn_lock_disposable_whitelist:
                        # now = datetime.datetime.now()
                        # user_disposable_whitelist_time = cache.get('add_svn_lock_disposable_whitelist_{}'.format(user))
                        # user_disposable_whitelist_time = datetime.datetime.strptime(
                        #     user_disposable_whitelist_time,
                        #     '%Y-%m-%d %H:%M:%S'
                        # )

                        # if user_disposable_whitelist_time + datetime.timedelta(hours=12) > now:
                        #     svn_lock_disposable_whitelist = [
                        #         rtx for rtx in svn_lock_disposable_whitelist if rtx != user
                        #     ]

                        #     branch_info.svn_lock_disposable_whitelist = ','.join(svn_lock_disposable_whitelist)
                        #     branch_info.save()

                        #     return JsonResponse({
                        #         "status": 500,
                        #         "message": "ok"
                        #     })

                        return JsonResponse({
                            "status": 200,
                            "message": "ok"
                        })

                    if user in svn_lock_blacklist:
                        return JsonResponse({
                            "status": 500,
                            "message": "ok"
                        })

                    if user in svn_lock_whitelist:
                        return JsonResponse({
                            "status": 200,
                            "message": "ok"
                        })

                    return JsonResponse({
                        "status": 500 if svn_lock_status else 200,
                        "message": "ok"
                    })

                return JsonResponse({
                    "code": RET.OK,
                    "msg": error_map[RET.OK],
                    "data": {
                        "branch": branch_info["svn_branch_name"],
                        "svn_lock_status": branch_info["svn_lock_status"],
                        "svn_lock_disposable_whitelist": branch_info["svn_lock_disposable_whitelist"],
                        "svn_lock_whitelist": branch_info["svn_lock_whitelist"],
                        "svn_lock_blacklist": branch_info["svn_lock_blacklist"],
                    }
                })
            else:
                return JsonResponse({
                    "code": RET.NODATA,
                    "msg": error_map[RET.NODATA],
                    "data": []
                })
        else:
            branch_info = SvnGitRelationInfo.objects.filter().order_by("-update_time").values()
            paginator = Paginator(branch_info, page_size)
            try:
                cur_page = paginator.page(page)
            except EmptyPage as e:
                return JsonResponse({"code": RET.PARAM_ERR, "msg": "找不到指定页", "data": {'err_msg': e}})

            return JsonResponse({
                "code": RET.OK,
                "msg": error_map[RET.OK],
                "data": [{
                    "branch": branch["svn_branch_name"],
                    "svn_lock_status": branch["svn_lock_status"],
                    "svn_lock_disposable_whitelist": branch["svn_lock_disposable_whitelist"],
                    "svn_lock_whitelist": branch["svn_lock_whitelist"],
                    "svn_lock_blacklist": branch["svn_lock_blacklist"],
                } for branch in cur_page],
                "total": paginator.count
            })

    def post(self, request):
        _data = json.loads(request.body.decode())
        """
        {
        "log": "--story= 添加队友弹幕stringID",
        "rep_name": "TIMIJ1/MSGame_proj",
        "paths": [
          "trunk/Common/Client/UnityProj/Assets/BundleResources/Prefab/UI/IG/IG_MainUI/"
        ],
        "files": [
          "U:trunk/Common/Client/UnityProj/Assets/BundleResources/Prefab/UI/IG/IG_MainUI/UI_IG_Main_GmPveadventure.prefab"
        ],
        "userName": "v_dljyliang",
        "revision": "380880-919c"
        }
        """

        log = _data.get("log", None)                # type: str
        rep_name = _data.get("rep_name", "")        # type: str
        paths = _data.get("paths", [])              # type: list[str]
        files = _data.get("files", [])              # type: list[str]
        user_name = _data.get("userName", "")       # type: str
        revision = _data.get("revision", "")        # type: str

        if not paths:
            return self.hook_response(**{
                "status": 500,
                "message": f"wrong parameter paths: {paths}"
            })

        first_path = paths[0]   # type: str
        if first_path.startswith("trunk"):
            branch = "trunk"
        else:
            branch = first_path.split("/")[1]

        # if not all([paths, files, user_name, revision]):
        #     return JsonResponse({
        #         "status": 500,
        #         "message": f"wrong parameter"
        #     })

        # 构建机账号，直接放行
        if user_name == "MSGameBuilder":
            return self.hook_response(**{
                "status": 200,
                "message": "ok"
            })

        # 临时屏蔽merge分支
        if branch == "research":
            return self.hook_response(**{
                "status": 200,
                "message": "ok"
            })

        # 特殊账号通过log获取实际操作用户
        if user_name == "MSGameDevCommon":
            search = re.search("(?i)submitter[:： ] *(\w+?\.)*(?P<user_name>\w+)", log)
            if search:
                user_name = search.group('user_name')
                logger.info("commit by MSGameDevCommon, submitter: {}".format(user_name))
            else:
                return self.hook_response(**{
                    "status": 500,
                    "message": "use MSGameDevCommon commit must with log like submitter: xxx"
                })

        if user_name == "dobbyy":
            search = re.search("(?i)author[:： ] *\w+", log)
            if search:
                user_name = search.group()[7:].strip()
                logger.info("commit by dobbyy, author: {}".format(user_name))
            else:
                return self.hook_response(**{
                    "status": 500,
                    "message": "use dobbyy commit must with log like author: xxx"
                })

        try:
            branch_info = SvnGitRelationInfo.objects.get(svn_branch_name=branch)
        except SvnGitRelationInfo.DoesNotExist as e:
            logger.warning(f"couldn't found branch: {branch}")
            return self.hook_response(**{
                "status": 200,
                "message": "ok"
            })

        regs = SvnLockReg.objects.filter(Q(branch__in=[branch_info]) | Q(branch=None), in_use=True)

        lock_status = branch_info.svn_lock_status
        svn_lock_blacklist = branch_info.svn_lock_blacklist.split(",") if branch_info.svn_lock_blacklist else []
        svn_lock_whitelist = branch_info.svn_lock_whitelist.split(",") if branch_info.svn_lock_whitelist else []
        svn_lock_disposable_whitelist = branch_info.svn_lock_disposable_whitelist.split(",") if branch_info.svn_lock_disposable_whitelist else []

        if log is not None:
            log = log.lower().strip()
            # log = log.strip()

            if not log:
                return self.hook_response(**{
                    "status": 500,
                    "message": "missing log, please commit with comments"
                })

            if len(files) > 900:
                # 超过900个文件，允许通过一次性白名单跳过检查（美术可能需要一次提交上万个文件）
                if user_name in svn_lock_disposable_whitelist:
                    svn_lock_disposable_whitelist.remove(user_name)
                    branch_info.svn_lock_disposable_whitelist = ",".join(svn_lock_disposable_whitelist)
                    branch_info.save()

                    logger.warning("{} use disposable whitelist, pass!".format(user_name))
                    return self.hook_response(**{
                        "status": 200,
                        "message": "ok"
                    })

                return self.hook_response(**{
                    "status": 500,
                    "message": "单次提交文件数量不允许超过900个文件"
                })

            # 文件通行证（阻挡），有管理员的需要管理员审批才可以提交
            file_regs = regs.filter(kind=1).exclude(administrator="").values(
                "id", "reg", "message", "administrator"
            )

            file_reg = None
            for reg in file_regs:
                try:
                    for file in files:
                        if re.search(reg['reg'], file):
                            file_review_user = reg['administrator'] if reg['administrator'] else "tobytian,ivylwang"

                            try:
                                apply = SvnFilePermissionApply.objects.get(
                                    apply_user=user_name, file_list=files, used=False
                                )
                            except SvnFilePermissionApply.DoesNotExist:
                                apply = None
                            if apply:
                                if apply.file_review_status == SvnFilePermissionApply.ReviewStatus.Reject:
                                    apply.used = True
                                    apply.save()

                                    return self.hook_response(**{
                                        "status": 500,
                                        "message": "提交包含需要审核才可提交的文件，审核已被拒绝！可以重新提交发起申请。".format(
                                            file_review_user
                                        )
                                    })
                                elif apply.file_review_status == SvnFilePermissionApply.ReviewStatus.Pass:
                                    apply.used = True
                                    apply.save()
                                else:
                                    return self.hook_response(**{
                                        "status": 500,
                                        "message": "提交包含需要审核才可提交的文件，已发送申请到svn提交群，请找{}进行文件审核!".format(
                                            file_review_user
                                        )
                                    })
                            else:
                                apply = SvnFilePermissionApply.objects.create(
                                    apply_id=f'{datetime.datetime.now().strftime("%Y%m%d%H%M%S")}',
                                    apply_user=user_name,
                                    file_review_user=file_review_user,
                                    file_list=files,
                                    svn_branch=branch
                                )

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
                                                "title": f"【{user_name}】文件提交审核申请",
                                                "desc": f"@{user_name}文件提交审核申请\n{user_name}，请{file_review_user}进行审批"
                                            },
                                            "horizontal_content_list": [
                                                {
                                                    "keyname": "点击详情查看",
                                                    "value": "详情",
                                                    "type": 1,
                                                    "url": f"https://{settings.CONF['BASE_CONF']['WEB_SERVER_IP']}/page/svnFilePermissionDetail?apply_id={apply.apply_id}"
                                                },
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
                                            "data": "发送企业微信消息失败！错误信息: {}".format(
                                                base_utils.bytes2str(result["errmsg"]))
                                        })
                                else:
                                    return JsonResponse({
                                        "code": RET.SERVER_ERR,
                                        "msg": error_map[RET.SERVER_ERR],
                                        "data": ["发送企业微信消息失败！错误信息:", base_utils.bytes2str(r.content)]
                                    })

                                return self.hook_response(**{
                                    "status": 500,
                                    "message": "提交包含需要审核才可提交的文件，已发送申请到svn提交群，请找{}进行文件审核!".format(
                                        reg['administrator'] if reg['administrator'] else "tobytian,ivylwang"
                                    )
                                })

                            file_reg = reg
                            break
                    if file_reg is not None:
                        break
                except re.error:
                    # 抓住错误的reg，谨防下毒！
                    logger.warning(f'wrong reg! {reg["reg"]}')
                    continue

            logger.info(f"svn svn_lock_disposable_whitelist: {svn_lock_disposable_whitelist}")
            # 一次性白名单在正常提交中最优先
            if user_name in svn_lock_disposable_whitelist:
                svn_lock_disposable_whitelist.remove(user_name)
                branch_info.svn_lock_disposable_whitelist = ",".join(svn_lock_disposable_whitelist)
                branch_info.save()

                logger.warning("{} use disposable whitelist, pass!".format(user_name))
                return self.hook_response(**{
                    "status": 200,
                    "message": "ok"
                })

            # 特殊通道
            # if log.find("--admin") != -1:
            #     return JsonResponse({
            #         "status": 200,
            #         "message": "ok"
            #     })

            # 文件通行证（阻挡）
            file_regs = regs.filter(kind=1, administrator="").values(
                "id", "reg", "message"
            )
            for reg in file_regs:
                try:
                    for file in files:
                        if re.search(reg["reg"], file):
                            message = reg["message"] if reg["message"] else "modify file {} is forbidden!".format(file)
                            logger.warning("{} {}, file: {}".format(user_name, message, file))
                            return self.hook_response(**{
                                "status": 500,
                                "message": message
                            })
                except re.error:
                    # 抓住错误的reg，谨防下毒！
                    logger.warning(f'wrong reg! {reg["reg"]}')
                    continue

            # 日志通行证（通行）
            log_regs = regs.filter(kind=0).values(
                "id", "reg", "message", "branch__svn_branch_name"
            )

            for reg in log_regs:
                if re.search(reg["reg"], log):
                    logger.info("{} use {} go through!".format(user_name, log))
                    return self.hook_response(**{
                        "status": 200,
                        "message": "ok"
                    })

            # 规范类，校验提交的规范性，不符合规范阻挡提交
            # if branch in ['trunk', 'Predistribution']:
            code, content = svn_hook_message.get_is_pass_by_log(log)
            if code:
                return self.hook_response(**content)

            if files:
                # meta文件漏提交检查
                add_or_delete_file_list = []
                add_or_delete_meta_file_list = []
                # lod文件漏提交检查
                prefab_list = []
                lod1_list = []
                lod2_list = []
                space_list = []

                for file in files:
                    # meta文件漏提交检查
                    if file.find("UnityProj/Assets/") != -1 or file.find("DSUnityProj/Assets/") != -1 or file.find("UnityProj/Packages/Shared/") != -1 or file.find("DSUnityProj/Packages/Shared/") != -1:
                        if file.startswith("A:"):
                            if file.lower().endswith(".meta"):
                                add_or_delete_meta_file_list.append(file.replace("A:", ""))
                            else:
                                add_or_delete_file_list.append(file.replace("A:", ""))
                        elif file.lower().startswith("D:"):
                            if file.lower().endswith(".meta"):
                                add_or_delete_meta_file_list.append(file.replace("D:", ""))
                            else:
                                add_or_delete_file_list.append(file.replace("D:", ""))

                    if file.find("UnityProj/Assets/Texture") != -1 or file.find("UnityProj/Assets/Texture_GVG") != -1:
                        if file.endswith(".jpg"):
                            return self.hook_response(**{
                                "status": 500,
                                "message": f"Texture/Texture_GVG folder is not allowed commit \".jpg\" file like \"{file}\""
                            })

                    _file = re.sub(r"^[ADU]:", "", file)
                    # lod文件漏提交检查
                    if _file.endswith("_LOD1.prefab"):
                        lod1_list.append(_file)
                    elif _file.endswith("_LOD2.prefab"):
                        lod2_list.append(_file)
                    elif _file.endswith(".prefab"):
                        prefab_list.append(_file)

                    # 命名检查
                    if not _file.endswith(".meta"):
                        # 文件名带空格检查
                        if " " in _file:
                            space_list.append(_file)
                        if (
                                _file.find("/Common/Client/UnityProj/Assets/") != -1
                                # 排除目录
                                and _file.find("/Editor/") == -1
                                and _file.find("/UnityProj/Assets/DesSource/LevelSource/Scene/GVGSandTable") == -1
                        ):
                            if re.search(u'[\u4e00-\u9fff]', _file.split("/Common/Client/UnityProj/Assets/")[1]):
                                return self.hook_response(**{
                                    "status": 500,
                                    "message": f"Assets文件夹下不能包含中文"
                                })
                        if _file.find("/Common/Client/UnityProj/Packages/msgame.share.assets") != -1:
                            package_path = _file.split("/Common/Client/UnityProj/Packages/msgame.share.assets")[1]
                            if len(package_path.split(".")) > 2:
                                return self.hook_response(**{
                                    "status": 500,
                                    "message": f"Packages下除了后缀不能包含\".\""
                                })

                            if re.search(u'[\u4e00-\u9fff]', _file.split("/Common/Client/UnityProj/Packages/msgame.share.assets/")[1]):
                                return self.hook_response(**{
                                    "status": 500,
                                    "message": f"msgame.share.assets文件夹下不能包含中文"
                                })

                if len(space_list) > 0:
                    send_str = '\n'.join(space_list)
                    return self.hook_response(**{"status": 500, "message": f"以下文件路径包含空格，请处理完再提交：\n{send_str}"})

                # meta文件漏提交检查
                for file in add_or_delete_file_list:
                    meta_file = file.rstrip("/").rstrip("\\") + ".meta"
                    if meta_file not in add_or_delete_meta_file_list:
                        file_name = [name for name in file.split("/") if name][-1]
                        file_name = file_name.split('.')[0]
                        if file_name != "":
                            return self.hook_response(**{
                                "status": 500,
                                "message": f"Adding/Deleting a file/folder('{file}') must be done with its meta file"
                            })

                # for file in add_or_delete_meta_file_list:
                #     owner_file = file.replace(".meta", "")
                #     if (owner_file not in add_or_delete_file_list) and f"{owner_file}/" not in add_or_delete_file_list:
                #         return JsonResponse({
                #             "status": 500,
                #             "message": f"Adding/Deleting a meta file('{file}') must be done with its owner file"
                #         })

                # lod文件漏提交检查
                prefab_list = svn_hook_message.filter_lod_path(prefab_list)
                if len(prefab_list) > 0:
                    for prefab_path in prefab_list:
                        lod1_path = prefab_path.split(".")[0] + "_LOD1.prefab"
                        lod2_path = prefab_path.split(".")[0] + "_LOD2.prefab"
                        if lod1_path not in lod1_list or lod2_path not in lod2_list:
                            return self.hook_response(**{
                                "status": 500,
                                "message": f"文件{prefab_path} 请提交lod1或者lod2"
                            })

            # message校验
            valid_code_review = svn_hook_message.get_is_code_review(user_name)
            logger.debug("valid_code_review: {}".format(valid_code_review))
            if valid_code_review:
                response = svn_hook_message.log_message_code_review(log, paths)
                logger.debug("valid_code_review response: {}".format(response))
            else:
                response = svn_hook_message.log_message_check(log, paths)
                logger.debug("not valid_code_review response: {}".format(response))
            if response != 0:
                return self.hook_response(**response)

            # bug list 监控
            valid_bug_review = svn_hook_message.get_is_bug_review(user_name)
            logger.debug("valid_bug_review: {}".format(valid_bug_review))
            if valid_bug_review:
                code, content = svn_hook_message.get_bug_id(log, paths)
                if code:
                    return self.hook_response(**content)
                else:
                    proj_reviewers = svn_hook_message.get_reviews_by_log(log)
                    if proj_reviewers == user_name:
                        return self.hook_response(**{
                            "status": 500,
                            "message": "reviewer can not only yourself!"
                        })

                    logger.debug("content: {}".format(content))
                    if log.find('--bug') != -1 and content == '0':
                        logger.info('--bug with ID 0, pass!')
                    elif content:
                        tapd = tapd_utils.Tapd(settings.CONF["TAPD"]["CLIENT_ID"], settings.CONF["TAPD"]["CLIENT_SECRET"])
                        code, content = tapd.get_is_bug(content)
                        logger.debug("tapd content: {}".format(content))
                        if code:
                            return self.hook_response(**content)

        # 黑名单第二
        if user_name in svn_lock_blacklist:
            return self.hook_response(**{
                "status": 500,
                "message": "you're in the blacklist!"
            })

        # 没有锁不需要判定白名单
        if not lock_status:
            logger.info("{} commit success!".format(user_name))
            return self.hook_response(**{
                "status": 200,
                "message": "ok"
            })

        # 有锁判定永久白名单
        if user_name in svn_lock_whitelist:
            logger.info("{} commit success with whitelist!".format(user_name))
            return self.hook_response(**{
                "status": 200,
                "message": "ok"
            })

        return self.hook_response(**{
            "status": 500,
            "message": "   ... Building Version ..... ..... Locked by PM ...     "
        })

    @staticmethod
    def put(request: "AsgiRequest"):

        _data = json.loads(request.body.decode())

        branch = _data.get("branch", "")
        kind = _data.get("kind", "")
        lock_status = _data.get("lockStatus", None)
        svn_lock_disposable_whitelist = _data.get("lockDisposableWhitelist", None)
        svn_lock_whitelist = _data.get("lockWhitelist", None)
        svn_lock_blacklist = _data.get("lockBlacklist", None)

        task_record = TaskRecord.create_log(
            operator=request.user,
            task_type=TaskRecord.TaskTypeEnum.SVNLock,
            post_json=json.dumps(_data),
            description=f'服务器刷表锁\n 分支:【{branch}】 锁状态:【{lock_status}】 一次性白名单:【{svn_lock_disposable_whitelist}】 永久白名单:【{svn_lock_whitelist}】 永久黑名单:【{svn_lock_blacklist}】'
        )

        branch_info = SvnGitRelationInfo.objects.get(svn_branch_name=branch)
        if lock_status is not None:
            branch_info.svn_lock_status = lock_status

        if svn_lock_disposable_whitelist is not None:
            if kind and kind == "add":
                db_data = branch_info.svn_lock_disposable_whitelist.split(",")
                add_data = list(filter(None, svn_lock_disposable_whitelist.split(",")))

                # now = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                # for rtx in add_data:
                #     cache.set('add_svn_lock_disposable_whitelist_{}'.format(rtx), now)

                db_data.extend(add_data)
                branch_info.svn_lock_disposable_whitelist = ",".join(db_data)
            elif kind and kind == "del":
                db_data = branch_info.svn_lock_disposable_whitelist.split(",")
                remove_data = list(filter(None, svn_lock_disposable_whitelist.split(",")))
                for rtx in remove_data:
                    if rtx in db_data:
                        db_data.remove(rtx)

                branch_info.svn_lock_disposable_whitelist = ",".join(db_data)
            else:
                branch_info.svn_lock_disposable_whitelist = svn_lock_disposable_whitelist

        if svn_lock_whitelist is not None:
            if kind and kind == "add":
                db_data = branch_info.svn_lock_whitelist.split(",")
                add_data = list(filter(None, svn_lock_whitelist.split(",")))
                db_data.extend(add_data)
                branch_info.svn_lock_whitelist = ",".join(list(set(db_data)))
            elif kind and kind == "del":
                db_data = branch_info.svn_lock_whitelist.split(",")
                remove_data = list(filter(None, svn_lock_whitelist.split(",")))
                for rtx in remove_data:
                    if rtx in db_data:
                        db_data.remove(rtx)

                branch_info.svn_lock_whitelist = ",".join(db_data)
            else:
                branch_info.svn_lock_whitelist = svn_lock_whitelist

        if svn_lock_blacklist is not None:
            if kind and kind == "add":
                db_data = branch_info.svn_lock_blacklist.split(",")
                add_data = list(filter(None, svn_lock_blacklist.split(",")))
                db_data.extend(add_data)
                branch_info.svn_lock_blacklist = ",".join(list(set(db_data)))
            elif kind and kind == "del":
                db_data = branch_info.svn_lock_blacklist.split(",")
                remove_data = list(filter(None, svn_lock_blacklist.split(",")))
                for rtx in remove_data:
                    if rtx in db_data:
                        db_data.remove(rtx)

                branch_info.svn_lock_blacklist = ",".join(db_data)
            else:
                branch_info.svn_lock_blacklist = svn_lock_blacklist

        branch_info.save()
        task_record.save_success({
            "branch": branch_info.svn_branch_name,
            "svn_lock_status": branch_info.svn_lock_status,
            "svn_lock_disposable_whitelist": branch_info.svn_lock_disposable_whitelist,
            "svn_lock_whitelist": branch_info.svn_lock_whitelist,
            "svn_lock_blacklist": branch_info.svn_lock_blacklist,
        })
        return JsonResponse({
            "code": RET.OK,
            "msg": error_map[RET.OK],
            "data": {
                "branch": branch_info.svn_branch_name,
                "svn_lock_status": branch_info.svn_lock_status,
                "svn_lock_disposable_whitelist": branch_info.svn_lock_disposable_whitelist,
                "svn_lock_whitelist": branch_info.svn_lock_whitelist,
                "svn_lock_blacklist": branch_info.svn_lock_blacklist,
            }
        })


class SvnLockPostCommitView(View):
    @staticmethod
    def post(request):
        _data = json.loads(request.body.decode())
        log = _data.get("log", None)                # type: str
        rep_name = _data.get("rep_name", "")        # type: str
        paths = _data.get("paths", [])              # type: list[str]
        files = _data.get("files", [])              # type: list[str]
        user_name = _data.get("userName", "")       # type: str
        revision = _data.get("revision", "")        # type: str

        first_path = paths[0]  # type: str
        if first_path.startswith("trunk"):
            svn_address = "/trunk/Common/Client"
        else:
            branch = first_path.split("/")[1]
            svn_address = f"/branches/{branch}/Common/Client"

        # proj_subject, proj_reviewers, proj_key = svn_hook_message.get_reviews_by_log(log)
        proj_subject, proj_reviewers, proj_key, svn_merge_dict = svn_hook_message.get_reviews_by_log(log)
        logger.info(f"proj_subject: {proj_subject}, proj_reviewers: {proj_reviewers}, proj_key: {proj_key}")
        if proj_key:
            tcr = TCR.objects.filter(key=proj_key).values()
            if len(tcr):
                create_patch_sets_review(svn_address, revision, user_name, tcr[0]["id"])
            elif proj_reviewers != "":
                create_svn_review(proj_subject, svn_address, revision, proj_reviewers, user_name, proj_key)

        if "REPOSITORY_TARGET" in svn_merge_dict:
            logger.debug("开始merge")
            source_svn = ""
            if svn_address == "/trunk/Common/Client":
                source_svn = "trunk"
            else:
                mach_obj = re.search("/branches/(\S+)/Common/Client", svn_address)
                if mach_obj:
                    source_svn = mach_obj.group(1)

            # 相同分支不进行merge操作
            if source_svn != svn_merge_dict["REPOSITORY_TARGET"]:
                resolve_conflict = "postpone"
                if "RESOLVE_CONFLICT" in svn_merge_dict:
                    resolve_conflict = svn_merge_dict["RESOLVE_CONFLICT"]

                merge_start_info = {
                    "Params": json.dumps({
                        "MERGE_TYPE": "normal",
                        "start_bus": "false",
                        "url": "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=14e4b6e4-38ef-473b-854d-bab132ccb547",
                        "RESOLVE_CONFLICT": resolve_conflict,
                        "APPLY_USERNAME": user_name,
                        "REPOSITORY_SOURCE": source_svn,
                        "SVNVERSION": str(revision),
                        "REPOSITORY_TARGET": svn_merge_dict["REPOSITORY_TARGET"],
                        "chatId": "wrkSFfCgAA9y58in-zajzZl4kMKEhfHQ"
                    }), "Command": "svn_merge", "User": user_name,
                    "Robot_URL": "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=14e4b6e4-38ef-473b-854d-bab132ccb547",
                    "Chat_ID": "wrkSFfCgAA9y58in-zajzZl4kMKEhfHQ"
                }

                headers = {
                    'Content-Type': 'application/json',
                    'X-DEVOPS-UID': 'v_hlhllu',
                    'X-Bkapi-Authorization': '{"bk_app_code": "errorlog",'
                                             '"bk_app_secret": "8ymLrmaXscFBkI9SSzsImGpRwhfcJmHiUh07",'
                                             '"access_token": "Oz9Ld0gzOmkyEJ9wRqIHCR0eAiBcuw",'
                                             '"bk_username": "v_hlhllu"'
                                             '}',
                }
                r = requests.post(
                    'https://devops.apigw.o.woa.com/prod/v4/apigw-user/projects/{}/build_start?pipelineId={}'.format(
                        "sworld", "p-87eafea90fdf4e8eada0d873bd886cb5"
                    ),
                    headers=headers,
                    json=merge_start_info)
                logger.debug("开始merge 发协议")
                if r.status_code == 200:
                    data = json.loads(r.text)["data"]
                    logger.debug(data)
                else:
                    raise Exception("Exception:DevopsUtil:build_start:status_code:{}".format(r.status_code))

        return JsonResponse({
            "status": 200,
            "message": "ok"
        })


class SvnLockRegView(View):
    @staticmethod
    def get(request):
        _branch = request.GET.get("branch", None)
        _reg = request.GET.get("reg", None)
        _page = request.GET.get('page', 1)
        _page_size = request.GET.get('page_size', 10)

        _items = SvnLockReg.objects

        if _branch:
            branches = SvnGitRelationInfo.objects.filter(branch_name__contains=_branch)

            _items = _items.filter(
                # Q(branch__svn_branch_name__contains=_branch) | Q(branch=None)
                Q(branch__in=branches) | Q(branch=None)
            )
        if _reg:
            _items = _items.filter(
                reg__contains=_reg
            )

        _items = _items.order_by("-id").all()

        # 分页
        paginator = Paginator(_items, _page_size)

        try:
            cur_page = paginator.page(_page)
        except EmptyPage:
            return JsonResponse({
                "code": RET.PARAM_ERR,
                "msg": "找不到指定页",
                "data": []
            })

        _data = []
        for _item in cur_page:
            _data.append({
                "id": _item.id,
                "branch": [branch.svn_branch_name for branch in _item.branch.all()],
                "reg": _item.reg,
                "message": _item.message,
                "kind": _item.kind,
                "administrator": _item.administrator,
                "in_use": _item.in_use,
            })

        return JsonResponse({
            "code": RET.OK,
            "msg": "检索成功",
            "data": _data,
            "count": paginator.num_pages
        })

    @staticmethod
    def post(request):
        _data = json.loads(request.body.decode())

        _id = _data.get("id")
        _reg = _data.get("reg", None)
        _message = _data.get("message", None)
        _kind = _data.get("kind", None)
        _branch = _data.get("branch", None)
        _administrator = _data.get("administrator", None)
        _in_use = _data.get("in_use", None)

        svn_lock_reg = SvnLockReg.objects.get(id=_id)

        if _reg is not None:
            svn_lock_reg.reg = _reg

        if _message is not None:
            svn_lock_reg.message = _message

        if _kind is not None:
            svn_lock_reg.kind = _kind

        if _branch is not None:
            svn_lock_reg.branch.clear()
            for branch in _branch:
                branch = SvnGitRelationInfo.objects.get(svn_branch_name=branch)
                svn_lock_reg.branch.add(branch)
            # branch = SvnGitRelationInfo.objects.get(svn_branch_name=_branch)
            # svn_lock_reg.branch = branch

        if _administrator is not None:
            svn_lock_reg.administrator = _administrator

        if _in_use is not None:
            svn_lock_reg.in_use = _in_use

        svn_lock_reg.save()

        return JsonResponse({
            "code": RET.OK,
            "msg": error_map[RET.OK],
            "data": {
                "id": svn_lock_reg.id,
                "reg": svn_lock_reg.reg,
                "message": svn_lock_reg.message,
                "kind": svn_lock_reg.kind,
                "branch": [branch.svn_branch_name for branch in svn_lock_reg.branch.all()],
                "administrator": svn_lock_reg.administrator,
                "in_use": svn_lock_reg.in_use,
            }
        })

    @staticmethod
    def put(request: "AsgiRequest"):
        _data = json.loads(request.body.decode())

        _reg = _data.get("reg", "")
        _message = _data.get("message", "")
        _kind = _data.get("kind", 0)
        _branch = _data.get("branch")
        _administrator = _data.get("administrator", "")

        if isinstance(request.user, AnonymousUser):
            return

        taskRecord = TaskRecord(
            operator=request.user,
            task_type=TaskRecord.TaskTypeEnum.SVNLockPermit,
            post_json=json.dumps(_data),
            description=f'服务器刷表锁\n 分支:【{_branch}】 匹配规则:【{_reg}】 提示语:【{_message}】 通行证类别:【{_kind}】'
        )

        svn_lock_reg = SvnLockReg.objects.create(
            reg=_reg, message=_message, kind=_kind, operator=request.user.account, administrator=_administrator
        )
        for branch in _branch:
            branch = SvnGitRelationInfo.objects.get(svn_branch_name=branch)
            svn_lock_reg.branch.add(branch)
        svn_lock_reg.save()
        # branch = SvnGitRelationInfo.objects.get(svn_branch_name=_branch)
        # svn_lock_reg = SvnLockReg.objects.create(reg=_reg, message=_message, kind=_kind, branch=branch, operator=request.user.account)

        taskRecord.save_success({
            "id": svn_lock_reg.id,
            "reg": svn_lock_reg.reg,
            "message": svn_lock_reg.message,
            "kind": svn_lock_reg.kind,
            "branch": [branch.svn_branch_name for branch in svn_lock_reg.branch.all()],
            "administrator": svn_lock_reg.administrator,
            "in_use": svn_lock_reg.in_use,
        })
        return JsonResponse({
            "code": RET.OK,
            "msg": error_map[RET.OK],
            "data": {
                "id": svn_lock_reg.id,
                "reg": svn_lock_reg.reg,
                "message": svn_lock_reg.message,
                "kind": svn_lock_reg.kind,
                "branch": [branch.svn_branch_name for branch in svn_lock_reg.branch.all()],
                "administrator": svn_lock_reg.administrator,
                "in_use": svn_lock_reg.in_use,
            }
        })

    @staticmethod
    def delete(request: "AsgiRequest"):
        _data = json.loads(request.body.decode())

        _id = _data.get("id")

        svn_lock_reg = SvnLockReg.objects.get(id=_id)
        svn_lock_reg.delete()

        return JsonResponse({
            "code": RET.OK,
            "msg": error_map[RET.OK],
            "data": {
                "id": svn_lock_reg.id,
            }
        })
