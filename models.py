# -*- coding:utf-8 -*-
import datetime

from django.core.cache import cache
from django.db import models

from dashboard.models import SvnGitRelationInfo
from utils.CustomModel import BaseModel

STATUS = (
    ("cancel", "取消"),
    ("kicked", "踢除"),
    ("running", "刷表中"),
    ("queue", "队列中"),
    ("conflict", "冲突"),
    ("timeout", "等待超时"),
    ("failed", "转表失败"),
    ("success", "刷表成功")
)

BUS_STATUS = (
    (0, "running"),
    (1, "success"),
    (2, "fail"),
)

REG_KIND = (
    (0, "log"),
    (1, "file"),
)


class SvnLockReg(BaseModel):
    id = models.AutoField(verbose_name="id", primary_key=True)
    reg = models.TextField(verbose_name="匹配规则", default="")
    message = models.TextField(verbose_name="提示语", default="")
    kind = models.SmallIntegerField(verbose_name="通行证类别", choices=REG_KIND, default=0)
    # block = models.BooleanField(verbose_name="阻止或通行", default=False)
    branch = models.ManyToManyField(SvnGitRelationInfo, null=True)
    administrator = models.TextField(verbose_name="管理员", default="")
    operator = models.CharField(verbose_name="最后操作人", default="", null=True, max_length=255)
    in_use = models.BooleanField(verbose_name="是否启用", default=True)

    class Meta:
        db_table = 'tb_svn_lock_reg'
        verbose_name = "SVN分支锁通行证"


class SVNPermissionApply(BaseModel):
    """SVN权限申请"""

    class ReviewStatus(models.IntegerChoices):
        """审核状态"""
        Pending = 0
        '''待审核'''
        Pass = 1
        '''通过'''
        Reject = 2
        '''拒绝'''

    apply_user = models.CharField(max_length=128, null=False, verbose_name='申请人账号')
    '''申请人账号'''
    apply_user_name = models.CharField(max_length=128, null=False, verbose_name='申请人账号名称')
    '''申请人账号名称'''
    review_user = models.CharField(max_length=128, null=False, verbose_name='审核人账号', default='')
    '''审核人账号'''
    review_user_name = models.CharField(max_length=128, null=False, verbose_name='审核人账号名称', default='')
    '''审核人账号名称'''
    svn_upload = models.BooleanField(max_length=128, null=False, verbose_name='SVN上传权限', default=False)
    '''SVN上传权限'''
    refresh_table = models.BooleanField(max_length=128, null=False, verbose_name='刷表权限', default=False)
    '''刷表权限'''
    permission_list = models.JSONField('权限列表对象', default=list)
    '''权限记录列表'''
    world_id = models.IntegerField(verbose_name='服务器id', null=False)
    '''服务器id'''
    review_status = models.SmallIntegerField(verbose_name='审核状态', choices=ReviewStatus.choices, default=ReviewStatus.Pending, null=False)
    '''审核状态'''
    svn_branch = models.CharField(max_length=128, null=False, verbose_name='SVN分支名', default='')

    class Meta:
        db_table = 'tb_svn_permission_apply'
        verbose_name = 'SVN权限申请记录'

    @staticmethod
    def rejectApply(review_user: str, user: str, world_id: int, branch: str):
        """拒绝申请"""
        obj, created = SVNPermissionApply.objects.update_or_create(defaults={
            'review_user_name': review_user,
            'review_user': review_user,
            'apply_user_name': user,
            'apply_user': user,
            'svn_upload': False,
            'refresh_table': False,
            'permission_list': [],
            'world_id': world_id,
            'review_status': SVNPermissionApply.ReviewStatus.Reject,
            'svn_branch': branch,
        }, apply_user=user, world_id=world_id)

        return obj

    @staticmethod
    def passApply(review_user: str, user: str, world_id: int, branch: str, svn_upload: bool = True, refresh_table: bool = True):
        """通过申请"""
        obj, created = SVNPermissionApply.objects.update_or_create(defaults={
            'review_user_name': review_user,
            'review_user': review_user,
            'apply_user_name': user,
            'apply_user': user,
            'svn_upload': svn_upload,
            'refresh_table': refresh_table,
            'permission_list': [],
            'world_id': world_id,
            'review_status': SVNPermissionApply.ReviewStatus.Pass,
            'svn_branch': branch,
        }, apply_user=user, world_id=world_id)

        if svn_upload:
            '''添加SVN锁一次性名单'''
            try:
                branch_info = SvnGitRelationInfo.objects.get(svn_branch_name=branch)
                if not branch_info.svn_lock_disposable_whitelist:
                    branch_info.svn_lock_disposable_whitelist = f'{user}'
                    branch_info.save()
                elif user not in branch_info.svn_lock_disposable_whitelist:
                    branch_info.svn_lock_disposable_whitelist += f',{user}'
                    branch_info.save()

            except SvnGitRelationInfo.DoesNotExist:
                pass

        if refresh_table:
            '''添加刷表锁一次性'''
            server_lock_whitelist = cache.get(f"server_lock_{world_id}_white_list", [])
            server_lock_whitelist.append(user)
            cache.set(f"server_lock_{world_id}_white_list", server_lock_whitelist, 60 * 60 * 24)

        return obj

    @staticmethod
    def addApply(user: str, world_id: int, branch: str, svn_upload: bool = True, refresh_table: bool = True):
        """添加申请"""
        obj, created = SVNPermissionApply.objects.update_or_create(defaults={
            'apply_user_name': user,
            'apply_user': user,
            'svn_upload': svn_upload,
            'refresh_table': refresh_table,
            'permission_list': [],
            'world_id': world_id,
            'review_status': SVNPermissionApply.ReviewStatus.Pending,
            'svn_branch': branch,
        }, apply_user=user, world_id=world_id)

        return obj


class SvnFilePermissionApply(BaseModel):
    """SVN文件锁权限申请"""

    class ReviewStatus(models.IntegerChoices):
        """审核状态"""
        Pending = 0
        '''待审核'''
        Pass = 1
        '''通过'''
        Reject = 2
        '''拒绝'''

    apply_id = models.CharField(max_length=128, null=False, verbose_name='申请ID')
    apply_user = models.CharField(max_length=128, null=False, verbose_name='申请人账号')
    '''申请人账号'''
    file_review_user = models.CharField(max_length=128, null=False, verbose_name='文件锁审核人账号', default='')
    svn_review_user = models.CharField(max_length=128, null=False, verbose_name='svn锁审核人账号', default='')
    '''审核人账号'''
    file_list = models.JSONField('需要审核的文件列表', default=list)
    '''权限记录列表'''
    file_review_status = models.SmallIntegerField(verbose_name='审核状态', choices=ReviewStatus.choices, default=ReviewStatus.Pending, null=False)
    svn_review_status = models.SmallIntegerField(verbose_name='审核状态', choices=ReviewStatus.choices, default=ReviewStatus.Pending, null=False)
    '''审核状态'''
    svn_branch = models.CharField(max_length=128, null=False, verbose_name='SVN分支名', default='')
    used = models.BooleanField(default=False)

    class Meta:
        db_table = 'tb_svn_file_permission_apply'
        verbose_name = 'SVN文件锁申请记录'


class TCR(BaseModel):
    id = models.CharField(verbose_name="tcrID", max_length=32, primary_key=True)
    key = models.TextField(verbose_name="tcrKEY", default="")

    class Meta:
        db_table = 'tb_tcr'
        verbose_name = "客户端review集"
