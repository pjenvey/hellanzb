# New ports collection makefile for:	hellanzb
# Date created:		Sat Sep 25 18:46:46 PDT 2004
# Whom:			Philip Jenveey <pjenvey@groovie.org>
#
# $FreeBSD$
# $Id$
#

PORTNAME=	hellanzb
PORTVERSION=	____VERSION____
#PORTEPOCH=	1
CATEGORIES?=	net
MASTER_SITES=	http://www.hellanzb.com/distfiles/
DISTNAME=	${PORTNAME}-${PORTVERSION}

PLIST_FILES=	bin/hellanzb.py \
		etc/hellanzb.conf.sample \
		share/doc/hellanzb/README \
		%%PYTHON_SITELIBDIR%%/Hellanzb/Core.py \
		%%PYTHON_SITELIBDIR%%/Hellanzb/Core.pyc \
		%%PYTHON_SITELIBDIR%%/Hellanzb/Core.pyo \
		%%PYTHON_SITELIBDIR%%/Hellanzb/Growl.py \
		%%PYTHON_SITELIBDIR%%/Hellanzb/Growl.pyc \
		%%PYTHON_SITELIBDIR%%/Hellanzb/Growl.pyo \
		%%PYTHON_SITELIBDIR%%/Hellanzb/PostProcessor.py \
		%%PYTHON_SITELIBDIR%%/Hellanzb/PostProcessor.pyc \
		%%PYTHON_SITELIBDIR%%/Hellanzb/PostProcessor.pyo \
		%%PYTHON_SITELIBDIR%%/Hellanzb/PostProcessorUtil.py \
		%%PYTHON_SITELIBDIR%%/Hellanzb/PostProcessorUtil.pyc \
		%%PYTHON_SITELIBDIR%%/Hellanzb/PostProcessorUtil.pyo \
		%%PYTHON_SITELIBDIR%%/Hellanzb/Logging.py \
		%%PYTHON_SITELIBDIR%%/Hellanzb/Logging.pyc \
		%%PYTHON_SITELIBDIR%%/Hellanzb/Logging.pyo \
		%%PYTHON_SITELIBDIR%%/Hellanzb/Util.py \
		%%PYTHON_SITELIBDIR%%/Hellanzb/Util.pyc \
		%%PYTHON_SITELIBDIR%%/Hellanzb/Util.pyo \
		%%PYTHON_SITELIBDIR%%/Hellanzb/Ziplick.py \
		%%PYTHON_SITELIBDIR%%/Hellanzb/Ziplick.pyc \
		%%PYTHON_SITELIBDIR%%/Hellanzb/Ziplick.pyo \
		%%PYTHON_SITELIBDIR%%/Hellanzb/__init__.py \
		%%PYTHON_SITELIBDIR%%/Hellanzb/__init__.pyc \
		%%PYTHON_SITELIBDIR%%/Hellanzb/__init__.pyo \
		%%PYTHON_SITELIBDIR%%/Hellanzb/Newsleecher/HeadHoncho.py \
		%%PYTHON_SITELIBDIR%%/Hellanzb/Newsleecher/HeadHoncho.pyc \
		%%PYTHON_SITELIBDIR%%/Hellanzb/Newsleecher/HeadHoncho.pyo \
		%%PYTHON_SITELIBDIR%%/Hellanzb/Newsleecher/NZBParser.py \
		%%PYTHON_SITELIBDIR%%/Hellanzb/Newsleecher/NZBParser.pyc \
		%%PYTHON_SITELIBDIR%%/Hellanzb/Newsleecher/NZBParser.pyo \
		%%PYTHON_SITELIBDIR%%/Hellanzb/Newsleecher/WrapNews.py \
		%%PYTHON_SITELIBDIR%%/Hellanzb/Newsleecher/WrapNews.pyc \
		%%PYTHON_SITELIBDIR%%/Hellanzb/Newsleecher/WrapNews.pyo \
		%%PYTHON_SITELIBDIR%%/Hellanzb/Newsleecher/WrapPost.py \
		%%PYTHON_SITELIBDIR%%/Hellanzb/Newsleecher/WrapPost.pyc \
		%%PYTHON_SITELIBDIR%%/Hellanzb/Newsleecher/WrapPost.pyo \
		%%PYTHON_SITELIBDIR%%/Hellanzb/Newsleecher/WrapServer.py \
		%%PYTHON_SITELIBDIR%%/Hellanzb/Newsleecher/WrapServer.pyc \
		%%PYTHON_SITELIBDIR%%/Hellanzb/Newsleecher/WrapServer.pyo \
		%%PYTHON_SITELIBDIR%%/Hellanzb/Newsleecher/__init__.py \
		%%PYTHON_SITELIBDIR%%/Hellanzb/Newsleecher/__init__.pyc \
		%%PYTHON_SITELIBDIR%%/Hellanzb/Newsleecher/__init__.pyo

PLIST_DIRS=	share/doc/hellanzb \
		%%PYTHON_SITELIBDIR%%/Hellanzb

RUN_DEPENDS=	nzbget:${POSTDIR}/news/nzbget \
		par2:${POSTDIR}/archivers/par2cmdline \
		rar:${POSTDIR}/archivers/rar \
		flac:${POSTDIR}/audio/flac \
		mac:${POSTDIR}/audio/mac \
		shorten:${POSTDIR}/audio/shorten

MAINTAINER=	pjenvey@groovie.org
COMMENT?=	Hands free usenet file retrieval via nzb files

USE_PYTHON=	yes
USE_PYDISTUTILS=	yes

post-install:

	@if [ ! -f ${LOCALBASE}/etc/hellanzb.conf ]; then \
		${ECHO} "Installing default configuration file."; \
		${INSTALL_DATA} ${WRKSRC}/etc/hellanzb.conf.sample ${LOCALBASE}/etc/hellanzb.conf; \
	fi

.include <bsd.port.mk>
