from django.urls import path
from . import views
from . import lock_queue_views

app_name = 'Lockapi'

urlpatterns = [
    path('config_refresh_lock/', views.ConfigRefreshLock.as_view()),
    path('config_refresh_force_unlock/', views.ConfigRefreshForceUnlock.as_view()),

    path('server_lock/', views.ServerLockView.as_view()),
    path('server_lock_whitelist/', views.ServerLockWhitelistView.as_view()),

    path('svn_lock/', lock_queue_views.SvnLockView.as_view()),
    path('svn_lock_reg/', lock_queue_views.SvnLockRegView.as_view()),
    path('svn_lock_post_commit/', lock_queue_views.SvnLockPostCommitView.as_view()),
    path('svn_permission_list/', views.SVNPermissionList.as_view(), name='获取svn锁权限列表'),
    path('svn_permission_detail/', views.SVNPermissionApplyDetail.as_view(), name='获取svn锁权限详情'),
    path('svn_permission_review/', views.SVNPermissionReview.as_view(), name='审核svn权限'),
    path('svn_permission_apply/', views.SVNPermissionApplyView.as_view(), name='申请svn权限'),

    path('svn_file_permission_detail/', views.SVNFilePermissionApplyDetail.as_view(), name='获取svn文件锁权限详情'),
    path('svn_file_permission_review/', views.SVNFilePermissionReview.as_view(), name='审核svn文件锁权限'),
]
