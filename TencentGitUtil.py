# -*- coding:utf-8 -*-
import json
import requests
import datetime
import time
import logging

from .models import TCR

logger = logging.getLogger(__package__)

headers = {
    'PRIVATE-TOKEN': '4XYBc4Tsa6J66X7Zg4Hv'
}
project_id = "975517"


# 获取一个单独用户的信息
# https://git.woa.com/help/menu/api/users.html
def get_users_id(reviewers):
    reviewer_ids = []
    reviewer_list = reviewers.split(",")
    for reviewer in reviewer_list:
        r = requests.get('https://git.woa.com/api/v3/users/{}'.format(reviewer), headers=headers)
        if r.status_code == 200:
            data = json.loads(r.text)
            if "id" in data:
                reviewer_ids.append(str(data["id"]))
        else:
            raise Exception("TencentGitUtil:get_users_id:status_code:{}".format(r.status_code))
    return ",".join(reviewer_ids)


# 新建 SVN 代码在服务器的评审
# https://git.woa.com/help/menu/api/svn/cr/svn_review.html
def create_svn_review(title, review_path, source_revision, reviewers, creator, proj_key):
    logger.info(
        f"create_svn_review---title:{title} review_path:{review_path} source_revision:{source_revision} reviewers:{reviewers} creator:{creator}")
    target_revision = source_revision - 1
    approver_rule = "-1"
    reviewer_ids = get_users_id(reviewers)
    request_link = "https://git.woa.com/api/v3/svn/projects/{}/reviews".format(project_id)
    json_data = {
        "title": title,
        "review_path": review_path,
        "source_revision": source_revision,
        "target_revision": target_revision,
        "reviewer_ids": reviewer_ids,
        "creator": creator,
        "approver_rule": approver_rule,
        "tapd_info": title,
    }
    r = requests.post(request_link, headers=headers, json=json_data)
    if r.status_code == 200:
        data = r.json()
        TCR.objects.update_or_create(id=data["id"], key=proj_key)
        logger.info(f"create_svn_review result: {data}")
    else:
        raise Exception("TencentGitUtil:create_svn_review:status_code:{}".format(r.status_code))


def get_reviews(page=1, pre_day=0):
    review_list = []
    r = requests.get('https://git.woa.com/api/v3/svn/projects/{}/reviews?page={}'.format(project_id, page),
                     headers=headers)
    if r.status_code == 200:
        datas = json.loads(r.text)
        if pre_day <= 0:
            review_list = datas
        else:
            for data in datas:
                dt = (datetime.datetime.strptime(data["created_at"], "%Y-%m-%dT%H:%M:%S%z") + datetime.timedelta(
                    hours=8)).strftime("%Y-%m-%d %H:%M:%S")
                # 转换成时间数组
                time_array = time.strptime(dt, "%Y-%m-%d %H:%M:%S")
                # 转换成时间戳
                time_stamp = time.mktime(time_array)
                if time_stamp > time.time() - pre_day * 24 * 60 * 60:
                    review_list.append(data)
        return review_list
    else:
        raise Exception("TencentGitUtil:get_reviews:status_code:{}".format(r.status_code))


# 获取 SVN 项目中所有的代码评审
# https://git.woa.com/help/menu/api/svn/cr/svn_review.html
def get_all_reviews(page=1, pre_day=0):
    review_list = []
    data = get_reviews(page, pre_day)
    count = len(data)
    if count > 0:
        review_list += data
        temp_list = get_all_reviews(page + 1, pre_day)
        if temp_list and len(temp_list) > 0:
            review_list += temp_list
    return review_list


# 新建 SVN 代码在服务器的修订集
# https://git.woa.com/help/menu/api/svn/cr/svn_review.html
def create_patch_sets_review(review_path, source_revision, user_name, review_id):
    logger.info(
        f"create_patch_sets_review---review_path:{review_path} source_revision:{source_revision} review_id:{review_id}")
    target_revision = source_revision - 1
    request_link = "https://git.woa.com/api/v3/svn/projects/{}/reviews/{}/patch_sets".format(project_id, review_id)
    json_data = {
        "review_path": review_path,
        "source_revision": source_revision,
        "target_revision": target_revision,
        "creator": user_name,
    }
    r = requests.post(request_link, headers=headers, json=json_data)
    if r.status_code == 200:
        logger.info(f"create_patch_sets_review result: {r.json()}")
    else:
        raise Exception("TencentGitUtil:create_patch_sets_review:status_code:{}".format(r.status_code))
