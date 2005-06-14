# New ports collection makefile for:	hellanzb
# Date created:		Sat Sep 25 18:46:46 PDT 2004
# Whom:			Philip Jenveey <pjenvey@groovie.org>
#
# $FreeBSD$
# $Id$
#

PORTNAME=	hellanzb
PORTVERSION=	____VERSION____
CATEGORIES=	news
MASTER_SITES=	http://www.hellanzb.com/distfiles/
DISTNAME=	${PORTNAME}-${PORTVERSION}

MAINTAINER=	pjenvey@groovie.org
COMMENT?=	nzb downloader and post processor

USE_PYTHON=	yes
USE_PYDISTUTILS=yes

RUN_DEPENDS=	par2:${PORTSDIR}/archivers/par2cmdline \
		rar:${PORTSDIR}/archivers/rar \
		flac:${PORTSDIR}/audio/flac \
		mac:${PORTSDIR}/audio/mac \
		shorten:${PORTSDIR}/audio/shorten \
		${PYTHON_SITELIBDIR}/twisted:${PORTSDIR}/devel/py-twistedCore \
		${PYTHON_SITELIBDIR}/twisted/web:${PORTSDIR}/www/py-twistedWeb

PLIST_FILES=	bin/hellanzb.py \
		etc/hellanzb.conf.sample \
		share/doc/hellanzb/CREDITS \
		share/doc/hellanzb/README \
		share/doc/hellanzb/LICENSE \
		%%PYTHON_SITELIBDIR%%/Hellanzb/Core.py \
		%%PYTHON_SITELIBDIR%%/Hellanzb/Core.pyc \
		%%PYTHON_SITELIBDIR%%/Hellanzb/Core.pyo \
		%%PYTHON_SITELIBDIR%%/Hellanzb/Daemon.py \
		%%PYTHON_SITELIBDIR%%/Hellanzb/Daemon.pyc \
		%%PYTHON_SITELIBDIR%%/Hellanzb/Daemon.pyo \
		%%PYTHON_SITELIBDIR%%/Hellanzb/Elite.py \
		%%PYTHON_SITELIBDIR%%/Hellanzb/Elite.pyc \
		%%PYTHON_SITELIBDIR%%/Hellanzb/Elite.pyo \
		%%PYTHON_SITELIBDIR%%/Hellanzb/Growl.py \
		%%PYTHON_SITELIBDIR%%/Hellanzb/Growl.pyc \
		%%PYTHON_SITELIBDIR%%/Hellanzb/Growl.pyo \
		%%PYTHON_SITELIBDIR%%/Hellanzb/HellaReactor.py \
		%%PYTHON_SITELIBDIR%%/Hellanzb/HellaReactor.pyc \
		%%PYTHON_SITELIBDIR%%/Hellanzb/HellaReactor.pyo \
		%%PYTHON_SITELIBDIR%%/Hellanzb/Log.py \
		%%PYTHON_SITELIBDIR%%/Hellanzb/Log.pyc \
		%%PYTHON_SITELIBDIR%%/Hellanzb/Log.pyo \
		%%PYTHON_SITELIBDIR%%/Hellanzb/Logging.py \
		%%PYTHON_SITELIBDIR%%/Hellanzb/Logging.pyc \
		%%PYTHON_SITELIBDIR%%/Hellanzb/Logging.pyo \
		%%PYTHON_SITELIBDIR%%/Hellanzb/PostProcessor.py \
		%%PYTHON_SITELIBDIR%%/Hellanzb/PostProcessor.pyc \
		%%PYTHON_SITELIBDIR%%/Hellanzb/PostProcessor.pyo \
		%%PYTHON_SITELIBDIR%%/Hellanzb/PostProcessorUtil.py \
		%%PYTHON_SITELIBDIR%%/Hellanzb/PostProcessorUtil.pyc \
		%%PYTHON_SITELIBDIR%%/Hellanzb/PostProcessorUtil.pyo \
		%%PYTHON_SITELIBDIR%%/Hellanzb/Util.py \
		%%PYTHON_SITELIBDIR%%/Hellanzb/Util.pyc \
		%%PYTHON_SITELIBDIR%%/Hellanzb/Util.pyo \
		%%PYTHON_SITELIBDIR%%/Hellanzb/__init__.py \
		%%PYTHON_SITELIBDIR%%/Hellanzb/__init__.pyc \
		%%PYTHON_SITELIBDIR%%/Hellanzb/__init__.pyo \
		%%PYTHON_SITELIBDIR%%/Hellanzb/HellaXMLRPC/HtPasswdAuth.py \
		%%PYTHON_SITELIBDIR%%/Hellanzb/HellaXMLRPC/HtPasswdAuth.pyc \
		%%PYTHON_SITELIBDIR%%/Hellanzb/HellaXMLRPC/HtPasswdAuth.pyo \
		%%PYTHON_SITELIBDIR%%/Hellanzb/HellaXMLRPC/__init__.py \
		%%PYTHON_SITELIBDIR%%/Hellanzb/HellaXMLRPC/__init__.pyc \
		%%PYTHON_SITELIBDIR%%/Hellanzb/HellaXMLRPC/__init__.pyo \
		%%PYTHON_SITELIBDIR%%/Hellanzb/HellaXMLRPC/xmlrpc.py \
		%%PYTHON_SITELIBDIR%%/Hellanzb/HellaXMLRPC/xmlrpc.pyc \
		%%PYTHON_SITELIBDIR%%/Hellanzb/HellaXMLRPC/xmlrpc.pyo \
		%%PYTHON_SITELIBDIR%%/Hellanzb/NZBLeecher/ArticleDecoder.py \
		%%PYTHON_SITELIBDIR%%/Hellanzb/NZBLeecher/ArticleDecoder.pyc \
		%%PYTHON_SITELIBDIR%%/Hellanzb/NZBLeecher/ArticleDecoder.pyo \
		%%PYTHON_SITELIBDIR%%/Hellanzb/NZBLeecher/NZBModel.py \
		%%PYTHON_SITELIBDIR%%/Hellanzb/NZBLeecher/NZBModel.pyc \
		%%PYTHON_SITELIBDIR%%/Hellanzb/NZBLeecher/NZBModel.pyo \
		%%PYTHON_SITELIBDIR%%/Hellanzb/NZBLeecher/NZBLeecherUtil.py \
		%%PYTHON_SITELIBDIR%%/Hellanzb/NZBLeecher/NZBLeecherUtil.pyc \
		%%PYTHON_SITELIBDIR%%/Hellanzb/NZBLeecher/NZBLeecherUtil.pyo \
		%%PYTHON_SITELIBDIR%%/Hellanzb/NZBLeecher/__init__.py \
		%%PYTHON_SITELIBDIR%%/Hellanzb/NZBLeecher/__init__.pyc \
		%%PYTHON_SITELIBDIR%%/Hellanzb/NZBLeecher/__init__.pyo \
		%%PYTHON_SITELIBDIR%%/Hellanzb/NZBLeecher/nntp.py \
		%%PYTHON_SITELIBDIR%%/Hellanzb/NZBLeecher/nntp.pyc \
		%%PYTHON_SITELIBDIR%%/Hellanzb/NZBLeecher/nntp.pyo

PLIST_DIRS=	share/doc/hellanzb \
		%%PYTHON_SITELIBDIR%%/Hellanzb/NZBLeecher \
		%%PYTHON_SITELIBDIR%%/Hellanzb

post-install:

	@if [ ! -f ${LOCALBASE}/etc/hellanzb.conf ]; then \
		${ECHO} "Installing default configuration file."; \
		${INSTALL_DATA} ${WRKSRC}/etc/hellanzb.conf.sample ${LOCALBASE}/etc/hellanzb.conf; \
	fi

.include <bsd.port.mk>
