# -*- coding:utf-8 -*-
import re
import io
import os
import logging

from autosystem import settings
from utils.base import tapd_utils

logger = logging.getLogger(__package__)


# 按行读取文本内容并返回
def file_read_lines(file_path):
    with io.open(file_path, 'r', encoding='utf-8') as f:
        lines = f.readlines()
    f.close()
    return lines


# 读取提交受限名单
def get_dic_by_file(file_path):
    lines = file_read_lines(file_path)
    dic_name = []
    if lines is not None and lines != '':
        for line in lines:
            line = line.strip()  # 去掉空格
            line = line.strip('\n')  # 去掉换行符
            if line != "":
                dic_name.append(line)
    return dic_name


# 获取code review标题和评审人列表
# def get_reviews_by_log(log, need_at=False):
#     reviewers_str = ""
#     reviewer_list = []
#     review_temp = log.split("review by")
#     if len(review_temp) == 2:
#         # reviewers = review_temp[1].replace(" ", "")
#         # reviewers = reviewers.replace(",", "")
#         # reviewers = reviewers.replace("，", "")
#         # if reviewers:
#         #     reviewer_list = reviewers[reviewers.find("@"):].split("@")
#         pat = re.compile('[@,，\s]')
#
#         if need_at:
#             if "@" in review_temp[1]:
#                 for reviewer in re.findall(r'\w+[^,，\s]', review_temp[1]):
#                     reviewer_list.append(pat.sub('', reviewer))
#         else:
#             for reviewer in re.findall(r'\w+[^,，\s]', review_temp[1]):
#                 reviewer_list.append(pat.sub('', reviewer))
#
#     if reviewer_list:
#         name_list = []
#         for name in reviewer_list:
#             if name != "":
#                 name_list.append(name)
#         reviewers_str = ",".join(name_list)
#
#     return reviewers_str


# 获取code review标题和评审人列表
def get_reviews_by_log(log):
    review_temp = log.split("review by")
    # 标题
    proj_subject = ""
    title = review_temp[0].strip()
    title = title.replace("\n", "")
    re_info = re.compile(r"--\S+=(.+)", re.M)
    m = re_info.search(title)
    if m:
        proj_subject = m.group()
    # 标题的key
    proj_key = ""
    m = re.search(r"--(\S+)=(\d+)", title, re.M)
    if m:
        proj_key = m.group(1) + m.group(2)

    reviewer_list = []
    reviewers_str = ""
    svn_merge_dict = {}
    if len(review_temp) >= 2:
        reviewers = review_temp[1].replace(" ", "")
        reviewers = "".join(reviewers.split("\n")[0].split())
        if reviewers:
            reviewers.strip()
            merge_info_list = reviewers.split("合线小助手")
            reviewer_list = merge_info_list[0].split("@")
            if len(merge_info_list) >= 2 and merge_info_list[1] != "":
                repository = merge_info_list[1]
                resolve_conflict = "postpone"
                if "覆盖" in merge_info_list[1]:
                    resolve_conflict = "theirs"
                    match_obj = re.search("(\S+)覆盖", merge_info_list[1])
                    if match_obj:
                        repository = match_obj.group(1)
                svn_merge_dict["REPOSITORY_TARGET"] = repository
                svn_merge_dict["RESOLVE_CONFLICT"] = resolve_conflict
        if len(reviewer_list) > 1:
            name_list = []
            for name in reviewer_list:
                if name != "" and name != "all":
                    name_list.append(re.sub('[\u4e00-\u9fa5]', '', name))
            reviewers_str = ",".join(name_list)
    else:
        log = log.replace(" ", "")
        log = log.split("\n")[0]
        if log:
            log.strip()
            merge_info_list = log.split("合线小助手")
            if len(merge_info_list) >= 2 and merge_info_list[1] != "":
                repository = merge_info_list[1]
                resolve_conflict = "postpone"
                if "覆盖" in merge_info_list[1]:
                    resolve_conflict = "theirs"
                    match_obj = re.search("(\S+)覆盖", merge_info_list[1])
                    if match_obj:
                        repository = match_obj.group(1)
                svn_merge_dict["REPOSITORY_TARGET"] = repository
                svn_merge_dict["RESOLVE_CONFLICT"] = resolve_conflict
    proj_subject = proj_subject.replace("\n", "")
    reviewers_str = reviewers_str.replace("\n", "")
    proj_key = proj_key.replace("\n", "")
    return proj_subject, reviewers_str, proj_key, svn_merge_dict


# 判断是否受code review 监控
def get_is_code_review(user_name):
    valid_code_review = False
    name_path = os.path.join('.', 'apps', 'Lockapi', 'code_review_list.txt')
    logger.info(f"name_path: {name_path}")
    if os.path.exists(name_path):
        list_name = get_dic_by_file(name_path)
        logger.info(f"list_name: {list_name}")
        if len(list_name) > 0:
            for name in list_name:
                if name == user_name:
                    valid_code_review = True
                    break
    return valid_code_review


# 判断是否受bug review监控
def get_is_bug_review(user_name):
    valid_bug_review = False
    name_path = os.path.join('.', 'apps', 'Lockapi', 'bug_review_list.txt')
    if os.path.exists(name_path):
        list_name = get_dic_by_file(name_path)
        if len(list_name) > 0:
            for name in list_name:
                if name == user_name:
                    valid_bug_review = True
                    break
    return valid_bug_review


# 过滤美术体路径
def filter_lod_path(prefab_list):
    result_list = []
    art_path = os.path.join('.', 'apps', 'Lockapi', 'art_path_list.txt')
    if os.path.exists(art_path):
        art_list = get_dic_by_file(art_path)
        if len(art_list) > 0:
            for prefab_path in prefab_list:
                for path in art_list:
                    if prefab_path.startswith(path):
                        result_list.append(prefab_path)
                        break
    return result_list


# 或bug_id
def get_bug_id(log, paths):
    for path in paths:
        if path.find("/Scripts/") != -1 or path.find("/ScriptsDS/") != -1 or path.find("LuaScript") != -1:
            valid_review_format = False
            valid_reviewer = False
            if log.find("review by") != -1:
                review_temp = log.split("review by")
                if len(review_temp) == 2:
                    reviewer = review_temp[1].replace(" ", "")
                    if reviewer:
                        valid_review_format = True
                        valid_reviewer = True

            if valid_review_format and valid_reviewer:
                break
            if not valid_review_format:
                return {
                    "status": 500,
                    "message": "Commit Code : You must add a reviewer(e.g. review by @arthuryu@v_hlhllu)"
                }

    if log.find("--bug=") != -1:
        if log.find("review by") != -1:
            re_info = re.compile(r"--bug=(\d+)")
            m = re_info.search(log)
            if m:
                bug_id = m.group(1)
                return 0, bug_id
            else:
                return -1, {
                    "status": 500,
                    "message": "Commit Code :wrong format --bug=0000000000"
                }
        else:
            return -1, {
                "status": 500,
                "message": "Commit Code :wrong format --bug=0000000000 review by @xxx"
            }
    else:
        return 0, 0


def get_is_pass_by_log(log):
    code, content = 0, ""
    tapd = tapd_utils.Tapd(settings.CONF["TAPD"]["CLIENT_ID"], settings.CONF["TAPD"]["CLIENT_SECRET"])
    if log.find("--story=") != -1 or log.find("--bug=") != -1 or log.find("--config=") != -1 or log.find("--task=") != -1:
        list_type = ["--bug=", "--story=", "--task="]
        for i in list_type:
            if log.find(i) != -1:
                re_info = re.compile(r"{}(\d+)".format(i))
                m = re_info.search(log)
                if m:
                    try:
                        type_id = m.group(1)
                        if int(type_id) == 0:
                            return -1, {
                                "status": 500,
                                "message": f"not right log format, Commit Code :填写的{i[2:-1]}ID不正确"
                            }
                    except ValueError:
                        return -1, {
                            "status": 500,
                            "message": f"not right log format, Commit Code :填写的{i[2:-1]}ID不正确"
                        }
                else:
                    return -1, {
                        "status": 500,
                        "message": f"not right log format, Commit Code :填写的{i[2:-1]}ID不正确"
                    }

                if type_id is not None:
                    if i == "--bug=":
                        code, content = tapd.get_is_bug(type_id)
                    elif i == "--story=":
                        code, content = tapd.get_is_story(type_id)
                    elif i == "--task=":
                        code, content = tapd.get_is_task(type_id)
                    elif i == "--config=":
                        code, content = 0, ""
                    else:
                        return -1, {
                            "status": 500,
                            "message": f"not right log format, Commit Code :填写的{i[2:-1]}ID不正确"
                        }
                    logger.debug("tapd code: {}, content: {}".format(code, content))
                    return code, content
                else:
                    return -1, {
                        "status": 500,
                        "message": "not right log format, please make sure svn log is started with --story=[TapdID] or --bug=[TapdID] or --task=[TapdID] "
                    }
    else:
        return -1, {
            "status": 500,
            "message": "not right log format, please make sure svn log is started with --story=[TapdID] or --bug=[TapdID] or --config=[config msg] or --task=[TapdID] "
        }
    return code, content


# message校验
def log_message_check(log, paths):
    if log.find("--story=") != -1 or log.find("--bug=") != -1 or log.find("--config=") != -1 or log.find("--task=") != -1:
        for path in paths:
            if path.find("/Scripts/") != -1 or path.find("/ScriptsDS/") != -1 or path.find("LuaScript") != -1:
                valid_review_format = False
                valid_reviewer = False
                if log.find("Merged revision") != -1:
                    valid_review_format = True
                    valid_reviewer = True
                if log.find("--story=svn merge") != -1:
                    valid_review_format = True
                    valid_reviewer = True
                if log.find("review by") != -1:
                    review_temp = log.split("review by")
                    if len(review_temp) == 2:
                        reviewer = review_temp[1].replace(" ", "")
                        if reviewer:
                            valid_review_format = True
                            valid_reviewer = True

                if valid_review_format and valid_reviewer:
                    break
                if not valid_review_format:
                    return {
                        "status": 500,
                        "message": "Commit Code : You must add a reviewer(e.g. review by @arthuryu@lukegao)"
                    }
    else:
        return {
            "status": 500,
            "message": "not right log format, please make sure svn log is started with --story=xxx or --bug=xxx or --config=xxx or --task=xxx "
        }
    return 0


# message code review
def log_message_code_review(log, paths):
    if log.find("--story=") != -1 or log.find("--bug=") != -1 or log.find("--config=") != -1 or log.find("--task=") != -1:
        for path in paths:
            if path.find("/Scripts/") != -1 or path.find("/ScriptsDS/") != -1 or path.find("LuaScript") != -1:
                valid_review_format = False
                valid_reviewer = False
                if log.find("review by") != -1:
                    if log.find("--bug=") != -1:
                        valid_review_format = True
                        valid_reviewer = True
                    elif log.find("Merged revision") != -1:
                        valid_review_format = True
                        valid_reviewer = True
                    elif log.find("--story=svn merge") != -1:
                        valid_review_format = True
                        valid_reviewer = True
                    elif log.find("@") != -1:
                        review_temp = log.split("review by")
                        if len(review_temp) == 2:
                            reviewers = review_temp[1].replace(" ", "")
                            if reviewers:
                                reviewers.strip()
                                reviewer_list = reviewers.split("@")
                                if len(reviewer_list) > 1:
                                    valid_review_format = True
                                    valid_reviewer = True
                    else:
                        return {
                            "status": 500,
                            "message": "Commit Code : You must add a reviewer and @ (e.g. review by @arthuryu@lukegao)"
                        }

                if valid_review_format and valid_reviewer:
                    break
                if not valid_review_format:
                    return {
                        "status": 500,
                        "message": "Commit Code : You must add a reviewer and @ (e.g. review by @arthuryu@lukegao)"
                    }
    else:
        return {
            "status": 500,
            "message": "not right log format, please make sure svn log is started with --story=xxx or --bug=xxx or --config=xxx or --task=xxx"
        }
    return 0


def change_tapd_review(user, log, review_list):
    if log.find("--bug=") != -1 or log.find("--task=") != -1:
        list_type = ["--bug=", "--task="]
        for i in list_type:
            type_id = None
            if log.find(i) != -1:
                re_info = re.compile(r"{}(\d+)".format(i))
                m = re_info.search(log)
                if m:
                    try:
                        type_id = m.group(1)
                        if int(type_id) == 0:
                            return -1, {
                                "status": 500,
                                "message": f"not right log format, Commit Code :填写的{i[2:-1]}ID不正确"
                            }
                    except ValueError:
                        return -1, {
                            "status": 500,
                            "message": f"not right log format, Commit Code :填写的{i[2:-1]}ID不正确"
                        }

            logger.debug('type_id: {}'.format(type_id))
            if type_id is not None:
                if i == '--bug=':
                    change_bug_review(user, type_id, review_list)
                elif i == '--task=':
                    change_task_review(user, type_id, review_list)
                break


def get_custom_field(data, name):
    for item in data:
        if "CustomFieldConfig" in item:
            CustomFieldConfig = item["CustomFieldConfig"]
            if "name" in CustomFieldConfig:
                if CustomFieldConfig["name"] == name:
                    custom_field = CustomFieldConfig["custom_field"]
                    return custom_field


def change_task_review(current_user, short_id, review_list):
    custom_field = {}
    tapd = tapd_utils.Tapd(settings.CONF["TAPD"]["CLIENT_ID"], settings.CONF["TAPD"]["CLIENT_SECRET"])
    long_id = tapd.get_long_by_short("task", short_id)
    data = tapd.get_task_custom_fields(long_id)
    custom_field_is_review = get_custom_field(data, "是否已经Review")
    custom_field_who_review = get_custom_field(data, "谁来review")
    if custom_field_is_review != "":
        data = tapd.get_task_by_id(long_id)
        custom_value = data[0]["Task"][custom_field_is_review]
        if custom_value == "已经review":
            custom_field[custom_field_is_review] = "还未review".encode("utf-8").decode("latin1")
    if custom_field_who_review != "":
        custom_field[custom_field_who_review] = review_list.encode("utf-8").decode("latin1")
    tapd.update_task_custom(current_user, long_id, custom_field)


def change_bug_review(current_user, short_id, review_list):
    custom_field = {}
    tapd = tapd_utils.Tapd(settings.CONF["TAPD"]["CLIENT_ID"], settings.CONF["TAPD"]["CLIENT_SECRET"])
    long_id = tapd.get_long_by_short("bug", short_id)
    data = tapd.get_bug_custom_fields(long_id)
    custom_field_is_review = get_custom_field(data, "是否已review")
    custom_field_who_review = get_custom_field(data, "review人")
    if custom_field_is_review != "":
        data = tapd.get_bug_by_id(long_id)
        custom_value = data[0]["Bug"][custom_field_is_review]
        if custom_value == "是":
            custom_field[custom_field_is_review] = "否".encode("utf-8").decode("latin1")
    if custom_field_who_review != "":
        custom_field[custom_field_who_review] = review_list.encode("utf-8").decode("latin1")
    tapd.update_bug_custom(current_user, long_id, custom_field)


def test():
    # pass
    # print(get_is_pass_by_log('--story=882141869 跳过角色查询GM时的找不到同玩好友的爆红 review by lukegao'))
    _log = "master_wff_1.12 (merge request !8587)\n    \n    Squash merge branch 'master_wff_1.12 into 'master'\n    \n    *  --task=75246055 【1.13】追捕计划改版-客户端-入口、解锁、图标替换、红点\n    【Submitter：wangfeifei_ns】\n     review by \xa0@simonlai\nwangfeifei_ns wangfeifei@sznshxxxkjyxg.wecom.work\n2024-08-22 15:03:00 +0800\n:2687:[codesync:28de43a458955521a919b1fcf7106b3f46fc3682]"
    # _path = ['trunk/Common/Client/GameData/Config/CN/xls/', 'trunk/Common/Client/GameData/Config/GLOBAL/xls/DTXml/']
    # print(log_message_code_review(_log, _path))
    proj_subject, reviewers_str, proj_key, svn_merge_dict = get_reviews_by_log(_log)
    print(f"proj_subject: {proj_subject}, reviewers_str: {reviewers_str}, proj_key: {proj_key}, svn_merge_dict: {svn_merge_dict}")
    # if proj_reviewers:
    #     print(code, content)
    # change_tapd_review('youchaowu', _log, ";".join(proj_reviewers.split(",")) + ";")
