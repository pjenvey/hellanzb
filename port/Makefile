# New ports collection makefile for:	hellanzb
# Date created:		Sat Sep 25 18:46:46 PDT 2004
# Whom:			#kgb
#
# $FreeBSD$
# $Id$
#

PORTNAME=	hellanzb
PORTVERSION=	____VERSION____
#PORTEPOCH=	1
CATEGORIES?=	net
#MASTER_SITES=	http://www.hellanzb.com/distfiles/
MASTER_SITES=	http://groovie.org/~pjenvey/
DISTNAME=	${PORTNAME}-${PORTVERSION}
NO_CHECKSUM=	yes

PLIST_FILES=	bin/hellanzb.py \
		etc/hellanzb.conf.sample \
		share/doc/hellanzb/README \
		%%PYTHON_SITELIBDIR%%/Hellanzb/Troll.py \
		%%PYTHON_SITELIBDIR%%/Hellanzb/Troll.pyc \
		%%PYTHON_SITELIBDIR%%/Hellanzb/Troll.pyo \
		%%PYTHON_SITELIBDIR%%/Hellanzb/Ziplick.py \
		%%PYTHON_SITELIBDIR%%/Hellanzb/Ziplick.pyc \
		%%PYTHON_SITELIBDIR%%/Hellanzb/Ziplick.pyo \
		%%PYTHON_SITELIBDIR%%/Hellanzb/__init__.py \
		%%PYTHON_SITELIBDIR%%/Hellanzb/__init__.pyc \
		%%PYTHON_SITELIBDIR%%/Hellanzb/__init__.pyo

PLIST_DIRS=	share/doc/hellanzb \
		%%PYTHON_SITELIBDIR%%/Hellanzb

MAINTAINER=	#kgb
COMMENT?=	leetness

USE_PYTHON=	yes
USE_PYDISTUTILS=	yes

post-install:

	@if [ ! -f ${LOCALBASE}/etc/hellanzb.conf ]; then \
		${ECHO} "Installing default configuration file."; \
		${INSTALL_DATA} ${WRKSRC}/etc/hellanzb.conf.sample ${LOCALBASE}/etc/hellanzb.conf; \
	fi

.include <bsd.port.mk>
