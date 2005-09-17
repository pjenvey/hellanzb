class HellanzbController < ApplicationController
  before_filter :authorize, :defaults
  before_filter :load_queue, :except => :dequeue
  before_filter :load_status, :except => :queue
  
  def index
    @asciiart = server.call('asciiart')
  end
  
  def queue
  end

  def dequeue
    nzb_id = params[:id].split("_")[1]
    server.call('dequeue', nzb_id)
  end

  def queuelist
    render :partial => "queue_list"
  end
  
  def update_order
    index = 0
    params[:nzb].each do |nzbId|
      if nzbId != @queue[index]["id"].to_s
        server.call('move', nzbId, index + 1)
      end
      index += 1
    end
  end
  
  def bandwidth
    if request.post?
      server.call('maxrate', params[:maxrate])
      session[:status] = nil
      load_status
    end
  end
  
  def enqueue_bookmarklet
    @id = params[:url].split('/')[-1]
    server.call('enqueuenewzbin', @id)
    redirect_to(params[:url])
  end
  
  def bookmarklet
      @mylink = "%s%s:%s" % [request.protocol,request.host,request.port]
  end
end